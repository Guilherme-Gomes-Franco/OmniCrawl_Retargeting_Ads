#!/usr/bin/env python3
import sqlite3
import zlib
import json
import csv
import glob
from pathlib import Path
import sys

def process_single_database(db_path, stats):
    """Processes a single .log.sqlite3 file and updates the master stats dictionary."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    print(f"[*] Processing: {db_path.name}")

    # --- 1. PROCESS CRAWL TABLE (RTB, CSync, UIDs) ---
    for browser_phase, url, timeout, data in cur.execute("SELECT browser, alexa_url, timeout, data FROM crawl"):
        if "Phase1B" in browser_phase:
            phase_key = "Pre"
        elif "Phase3" in browser_phase:
            phase_key = "Post"
        else:
            continue  # Skip Phase 1A Seeder sites

        try:
            obj = json.loads(zlib.decompress(data).decode("utf-8", "ignore"))
        except Exception:
            continue

        if url not in stats:
            stats[url] = {
                "Pre": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0},
                "Post": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0},
                "js_exceptions_unique": 0
            }

        requests = obj.get('requests', [])
        for req in requests:
            etr = req.get('etr_metrics', {})
            
            # Safe Float Conversion (Prevents crash on UUID strings)
            cpm = etr.get('max_cpm')
            if cpm is not None:
                try:
                    cpm_val = float(cpm)
                    if cpm_val > stats[url][phase_key]["max_cpm"]:
                        stats[url][phase_key]["max_cpm"] = cpm_val
                except (ValueError, TypeError):
                    pass

            if etr.get('is_rtb'):
                stats[url][phase_key]["auctions"] += 1
            if etr.get('is_csync'):
                stats[url][phase_key]["syncs"] += 1
            if etr.get('smuggled_uids'):
                stats[url][phase_key]["uids"] += len(etr.get('smuggled_uids', []))

    # --- 2. PROCESS JS_EXCEPTIONS TABLE (Site Breakage) ---
    try:
        cur.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='js_exceptions'")
        if cur.fetchone()[0] > 0:
            for url, fingerprint_count in cur.execute(
                "SELECT url, COUNT(DISTINCT fingerprint) FROM js_exceptions GROUP BY url"
            ):
                if url in stats:
                    stats[url]["js_exceptions_unique"] += fingerprint_count
    except Exception as e:
        pass

    conn.close()

def export_unified_comparison(stats, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Website", 
            "Pre-Break Max CPM ($)", "Post-Break Max CPM ($)", "CPM Delta (%)",
            "Pre-Break Syncs", "Post-Break Syncs", "Sync Delta",
            "Pre-Break UIDs", "Post-Break UIDs",
            "Unique JS Exceptions",
            "Tracking Resistance Verdict"
        ])

        summary_counts = {"HIGH": 0, "LOW": 0, "PARTIAL": 0, "NO_AUCTION": 0}

        for site, data in sorted(stats.items()):
            pre_cpm = data["Pre"]["max_cpm"]
            post_cpm = data["Post"]["max_cpm"]
            
            # SCIENTIFIC VERDICT LOGIC
            if pre_cpm == 0.0 and post_cpm == 0.0:
                cpm_delta_str = "N/A"
                verdict = "NO AUCTION DETECTED"
                summary_counts["NO_AUCTION"] += 1
            elif pre_cpm == 0.0 and post_cpm > 0.0:
                cpm_delta_str = "+INF (Post Only)"
                verdict = "LOW RESISTANCE (Ad Appeared Post-Break)"
                summary_counts["LOW"] += 1
            else:
                cpm_delta = ((post_cpm - pre_cpm) / pre_cpm) * 100.0
                cpm_delta_str = f"{round(cpm_delta, 2)}%"
                
                # ETR Criteria:
                # Dropped by >= 30% -> High tracking resistance (Persona broken)
                if cpm_delta <= -30.0:
                    verdict = "HIGH RESISTANCE (Persona Lost)"
                    summary_counts["HIGH"] += 1
                elif cpm_delta >= -10.0:
                    verdict = "LOW RESISTANCE (Tracking Persisted)"
                    summary_counts["LOW"] += 1
                else:
                    verdict = "PARTIAL RESISTANCE"
                    summary_counts["PARTIAL"] += 1

            sync_delta = data["Post"]["syncs"] - data["Pre"]["syncs"]

            writer.writerow([
                site,
                f"{pre_cpm:.4f}", f"{post_cpm:.4f}", cpm_delta_str,
                data["Pre"]["syncs"], data["Post"]["syncs"], sync_delta,
                data["Pre"]["uids"], data["Post"]["uids"],
                data["js_exceptions_unique"],
                verdict
            ])

    print("\n========================================================")
    print(f"   ANALYSIS COMPLETE: {output_path.name}")
    print(f"   Total Sites Analyzed: {len(stats)}")
    print(f"   - High Resistance (Persona Wiped): {summary_counts['HIGH']}")
    print(f"   - Partial Resistance:              {summary_counts['PARTIAL']}")
    print(f"   - Low / Tracking Persisted:        {summary_counts['LOW']}")
    print(f"   - No Transparent Auction (0 vs 0): {summary_counts['NO_AUCTION']}")
    print("========================================================\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Single DB:   python compare.py ETR_data/chrome_baseline_38080_*.log.sqlite3")
        print("  Merge all 3: python compare.py ETR_data/chrome_baseline_*.log.sqlite3")
        sys.exit(1)

    # Collect all matching files (supports wildcards or single paths)
    input_patterns = sys.argv[1:]
    matched_files = []
    for pattern in input_patterns:
        files = glob.glob(pattern)
        if files:
            matched_files.extend(files)
        elif Path(pattern).exists():
            matched_files.append(pattern)

    matched_files = sorted(list(set(matched_files)))
    if not matched_files:
        print("[!] No matching database files found.")
        sys.exit(1)

    master_stats = {}
    for db_file in matched_files:
        process_single_database(Path(db_file), master_stats)

    # Generate a descriptive output name based on the first file's prefix
    first_stem = Path(matched_files[0]).stem
    # Extracts e.g. "chrome_baseline" from "chrome_baseline_38080_..."
    parts = first_stem.split('_')
    prefix = f"{parts[0]}_{parts[1]}" if len(parts) >= 2 else first_stem
    
    output_csv = Path("output") / f"comparison_{prefix}_merged.csv"
    export_unified_comparison(master_stats, output_csv)