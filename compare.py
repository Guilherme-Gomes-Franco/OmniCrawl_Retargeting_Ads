#!/usr/bin/env python3
import sqlite3
import zlib
import json
import csv
from pathlib import Path
import sys

def process_database(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Structure: results[site][phase] = {metrics}
    stats = {}

    print(f"[*] Processing {db_path.name}...")

    for browser_phase, url, timeout, data in cur.execute("SELECT browser, alexa_url, timeout, data FROM crawl"):
        # Identify the phase (PreBreak vs PostBreak)
        if "Phase1B" in browser_phase:
            phase_key = "Pre"
        elif "Phase3" in browser_phase:
            phase_key = "Post"
        else:
            continue # Skip Phase 1A Training sites as they don't have measurements

        try:
            obj = json.loads(zlib.decompress(data).decode("utf-8", "ignore"))
        except:
            continue

        if url not in stats:
            stats[url] = {"Pre": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0},
                          "Post": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0}}

        requests = obj.get('requests', [])
        for req in requests:
            etr = req.get('etr_metrics', {})
            
            # Aggregate Max CPM seen on this page
            cpm = etr.get('max_cpm')
            if cpm and float(cpm) > stats[url][phase_key]["max_cpm"]:
                stats[url][phase_key]["max_cpm"] = float(cpm)
            
            if etr.get('is_rtb'):
                stats[url][phase_key]["auctions"] += 1
            
            if etr.get('is_csync'):
                stats[url][phase_key]["syncs"] += 1
            
            if etr.get('smuggled_uids'):
                stats[url][phase_key]["uids"] += len(etr.get('smuggled_uids', []))

    conn.close()
    return stats

def export_comparison(stats, output_name):
    with open(output_name, "w", newline='') as f:
        writer = csv.writer(f)
        # Header for Thesis Analysis
        writer.writerow([
            "Website", 
            "Pre-Break Max CPM", "Post-Break Max CPM", "CPM Delta (%)",
            "Pre-Break Syncs", "Post-Break Syncs", "Sync Delta",
            "Pre-Break UIDs", "Post-Break UIDs",
            "Tracking Resistance Verdict"
        ])

        for site, data in stats.items():
            pre_cpm = data["Pre"]["max_cpm"]
            post_cpm = data["Post"]["max_cpm"]
            
            # Calculate CPM % Change
            if pre_cpm > 0:
                cpm_delta_pct = round(((post_cpm - pre_cpm) / pre_cpm) * 100, 2)
            else:
                cpm_delta_pct = 0.0

            sync_delta = data["Post"]["syncs"] - data["Pre"]["syncs"]
            
            # Determine Verdict
            # High Resistance = CPM dropped significantly after identity break
            if cpm_delta_pct < -30:
                verdict = "HIGH RESISTANCE (Persona Lost)"
            elif cpm_delta_pct > -10:
                verdict = "LOW RESISTANCE (Tracking Persisted)"
            else:
                verdict = "PARTIAL"

            writer.writerow([
                site,
                pre_cpm, post_cpm, f"{cpm_delta_pct}%",
                data["Pre"]["syncs"], data["Post"]["syncs"], sync_delta,
                data["Pre"]["uids"], data["Post"]["uids"],
                verdict
            ])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare.py ETR_data/$browser_$Flag_$proxy_$date.log.sqlite3")
        sys.exit(1)

    db_path = Path(sys.argv[1])
    results = process_database(db_path)
    
    output_file = f"output/comparison_{db_path.stem}.csv"
    export_comparison(results, output_file)
    print(f"[!] Comparison complete: {output_file}")