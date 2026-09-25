#!/usr/bin/env python3
"""
ETR Master Thesis Analysis Pipeline
Automates:
  1. Worker batch merging per browser configuration
  2. Heartbeat CSV fusion (CMP consent & timing)
  3. Economic Delta (CPM) & Identity Leakage (CSync/UIDs)
  4. Site Breakage Index (SBI) normalized to Chrome Baseline
  5. Statistical Significance Testing (Wilcoxon Signed-Rank & Kruskal-Wallis)
  6. Thesis Summary Table Generation
"""

import sqlite3
import zlib
import json
import csv
import glob
import re
import math
from pathlib import Path
import numpy as np
from scipy import stats

DATA_DIR = Path("ETR_data")
OUTPUT_DIR = Path("thesis_results")
OUTPUT_DIR.mkdir(exist_ok=True)

# The 5 target configurations
CONFIGS = [
    "chrome_baseline",
    "firefox_baseline",
    "firefox_hardened",
    "brave_baseline",
    "brave_hardened",
]

def compute_metrics(browser_summary):
    """
    Computes exact Chapter 5 metrics:
      - Extraction Yield (Section 5.1.2)
      - R_ID, D_ID, U_cost, and composite ETR (Section 5.3.1)
    """
    total_attempts = browser_summary["total_sites"]
    successful_trials = browser_summary["successful_sites"]
    
    # Section 5.1.2: Extraction Yield
    extraction_yield = (successful_trials / total_attempts) * 100.0 if total_attempts > 0 else 0.0

    # Section 5.2.1: Re-identification Rate (Fraction of sites where tracking persisted)
    active = browser_summary["active_auction_sites"]
    r_id = (browser_summary["low_res_count"] / active) if active > 0 else 0.0

    # Section 5.2.2: Identity Diffusion (Phase 3 Syncs + UIDs)
    d_id = browser_summary["post_syncs_total"] + browser_summary["post_uids_total"]

    # Section 5.3.1: Usability Cost U_cost (Excess breakage over Chrome Baseline)
    sbi = browser_summary["mean_sbi"]
    u_cost = max(0.0, sbi - 1.0)

    # Section 5.3.1: ETR Formula
    # ETR = [ (1 - R_ID) * (1 / log(D_ID + e)) ] / [ 1 + U_cost ]
    diffusion_factor = 1.0 / math.log(d_id + math.e)
    etr_score = ((1.0 - r_id) * diffusion_factor) / (1.0 + u_cost)

    return {
        "extraction_yield": round(extraction_yield, 2),
        "r_id": round(r_id, 3),
        "d_id": d_id,
        "u_cost": round(u_cost, 3),
        "etr_score": round(etr_score, 4)
    }

def load_heartbeat_data():
    """Reads all heartbeat CSVs to map domain -> {status, cmp_method, duration}."""
    hb_map = {} # (browser_config, domain) -> dict
    for csv_file in DATA_DIR.glob("heartbeat_*.csv"):
        stem = csv_file.stem.replace("heartbeat_", "")
        # Match configuration prefix
        config = None
        for c in CONFIGS:
            if stem.startswith(c):
                config = c
                break
        if not config:
            continue

        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    site = row.get("site", "").strip()
                    if not site:
                        continue
                    key = (config, site)
                    # Keep latest or most successful status
                    if key not in hb_map or row.get("status") == "SUCCESS":
                        hb_map[key] = {
                            "status": row.get("status", "UNKNOWN"),
                            "cmp_method": row.get("cmp_method", "NONE"),
                            "duration_sec": row.get("duration_sec", "0")
                        }
        except Exception as e:
            print(f"[!] Warning loading {csv_file.name}: {e}")
    return hb_map

def extract_database_metrics(db_path, browser_data):
    """Parses a single .log.sqlite3 file and aggregates per-domain stats."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    for browser_phase, url, timeout, data in cur.execute("SELECT browser, alexa_url, timeout, data FROM crawl"):
        if "Phase1B" in browser_phase:
            phase = "Pre"
        elif "Phase3" in browser_phase:
            phase = "Post"
        else:
            continue  # Ignore Phase 1A Seeder training

        try:
            payload = json.loads(zlib.decompress(data).decode("utf-8", "ignore"))
        except Exception:
            continue

        if url not in browser_data:
            browser_data[url] = {
                "Pre": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0},
                "Post": {"max_cpm": 0.0, "syncs": 0, "uids": 0, "auctions": 0},
                "unique_exceptions": set()
            }

        requests = payload.get("requests", [])
        for req in requests:
            etr = req.get("etr_metrics", {})

            # Safe extraction of max numeric CPM
            cpm = etr.get("max_cpm")
            if cpm is not None:
                try:
                    cpm_f = float(cpm)
                    if cpm_f > browser_data[url][phase]["max_cpm"]:
                        browser_data[url][phase]["max_cpm"] = cpm_f
                except (ValueError, TypeError):
                    pass

            if etr.get("is_rtb"):
                browser_data[url][phase]["auctions"] += 1
            if etr.get("is_csync"):
                browser_data[url][phase]["syncs"] += 1
            if etr.get("smuggled_uids"):
                browser_data[url][phase]["uids"] += len(etr.get("smuggled_uids", []))

    # Pull JS exceptions if table exists
    try:
        cur.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='js_exceptions'")
        if cur.fetchone()[0] > 0:
            for url, fp in cur.execute("SELECT url, fingerprint FROM js_exceptions"):
                if url in browser_data and fp:
                    browser_data[url]["unique_exceptions"].add(fp)
    except Exception:
        pass

    conn.close()

def run_analysis():
    print("==========================================================")
    print("   ETR MASTER THESIS STATISTICAL & CAUSAL EVALUATION      ")
    print("==========================================================\n")

    hb_data = load_heartbeat_data()
    print(f"[*] Loaded heartbeat metadata for {len(hb_data)} browser-site pairs.")

    # 1. Ingest and merge all workers per browser configuration
    dataset = {}  # config -> { domain -> metrics }
    for config in CONFIGS:
        dataset[config] = {}
        # Find all log databases matching this config (e.g., chrome_baseline_38080_*.log.sqlite3)
        pattern = str(DATA_DIR / f"{config}_*.log.sqlite3")
        db_files = sorted(glob.glob(pattern))

        if not db_files:
            # Check for legacy single-file naming
            fallback = DATA_DIR / f"{config}.log.sqlite3"
            if fallback.exists():
                db_files = [str(fallback)]

        print(f"[*] Processing {config}: found {len(db_files)} database slice(s).")
        for db in db_files:
            extract_database_metrics(db, dataset[config])

    # 2. Compute Chrome Baseline Error Count for SBI normalisation
    chrome_exceptions = {}
    for url, data in dataset.get("chrome_baseline", {}).items():
        chrome_exceptions[url] = max(1, len(data["unique_exceptions"]))  # Floor at 1 to prevent div by 0

    # 3. Export Per-Browser Master CSVs
    per_browser_summaries = {}
    for config, sites in dataset.items():
        if not sites:
            continue

        csv_path = OUTPUT_DIR / f"master_{config}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Domain", "Status", "CMP_Method",
                "Pre_Max_CPM", "Post_Max_CPM", "CPM_Delta_Pct",
                "Pre_Syncs", "Post_Syncs", "Sync_Delta",
                "Pre_UIDs", "Post_UIDs",
                "Unique_Exceptions", "Site_Breakage_Index",
                "Verdict"
            ])

            deltas = []
            verdicts = {"HIGH": 0, "PARTIAL": 0, "LOW": 0, "NO_AUCTION": 0}
            pre_bids_all = []
            post_bids_all = []
            sbi_scores = []
            successful_count = 0
            post_syncs_sum = 0
            post_uids_sum = 0

            for url, m in sorted(sites.items()):
                pre_cpm = m["Pre"]["max_cpm"]
                post_cpm = m["Post"]["max_cpm"]
                hb_info = hb_data.get((config, url), {"status": "SUCCESS", "cmp_method": "DOM/API"})

                if hb_info["status"] == "SUCCESS":
                    successful_count += 1

                post_syncs_sum += m["Post"]["syncs"]
                post_uids_sum += m["Post"]["uids"]

                # Scientific Verdict & Delta
                if pre_cpm == 0.0 and post_cpm == 0.0:
                    delta_str = "N/A"
                    verdict = "NO_AUCTION"
                    verdicts["NO_AUCTION"] += 1
                elif pre_cpm == 0.0 and post_cpm > 0.0:
                    delta_str = "+INF"
                    verdict = "LOW (Post-Only)"
                    verdicts["LOW"] += 1
                    pre_bids_all.append(pre_cpm)
                    post_bids_all.append(post_cpm)
                else:
                    delta = ((post_cpm - pre_cpm) / pre_cpm) * 100.0
                    delta_str = f"{delta:.2f}%"
                    deltas.append(delta)
                    pre_bids_all.append(pre_cpm)
                    post_bids_all.append(post_cpm)

                    if delta <= -30.0:
                        verdict = "HIGH (Persona Wiped)"
                        verdicts["HIGH"] += 1
                    elif delta >= -10.0:
                        verdict = "LOW (Tracking Persisted)"
                        verdicts["LOW"] += 1
                    else:
                        verdict = "PARTIAL"
                        verdicts["PARTIAL"] += 1

                # SBI Calculation
                raw_errors = len(m["unique_exceptions"])
                base_errors = chrome_exceptions.get(url, 1)
                sbi = round(raw_errors / base_errors, 2)
                sbi_scores.append(sbi)

                sync_delta = m["Post"]["syncs"] - m["Pre"]["syncs"]

                writer.writerow([
                    url, hb_info["status"], hb_info["cmp_method"],
                    f"{pre_cpm:.4f}", f"{post_cpm:.4f}", delta_str,
                    m["Pre"]["syncs"], m["Post"]["syncs"], sync_delta,
                    m["Pre"]["uids"], m["Post"]["uids"],
                    raw_errors, sbi,
                    verdict
                ])

            # Store summary stats for cross-browser synthesis
            active_sites = verdicts["HIGH"] + verdicts["PARTIAL"] + verdicts["LOW"]
            summary_dict = {
                "total_sites": len(sites),
                "successful_sites": successful_count,
                "active_auction_sites": active_sites,
                "high_res_count": verdicts["HIGH"],
                "low_res_count": verdicts["LOW"],
                "partial_count": verdicts["PARTIAL"],
                "high_res_pct": round((verdicts["HIGH"] / active_sites) * 100, 2) if active_sites > 0 else 0.0,
                "partial_pct": round((verdicts["PARTIAL"] / active_sites) * 100, 2) if active_sites > 0 else 0.0,
                "low_res_pct": round((verdicts["LOW"] / active_sites) * 100, 2) if active_sites > 0 else 0.0,
                "median_cpm_delta": round(float(np.median(deltas)), 2) if deltas else 0.0,
                "mean_sbi": round(float(np.mean(sbi_scores)), 2) if sbi_scores else 1.0,
                "post_syncs_total": post_syncs_sum,
                "post_uids_total": post_uids_sum,
                "pre_bids": pre_bids_all,
                "post_bids": post_bids_all,
                "all_deltas": deltas
            }

            # ---> HERE IS WHERE YOU CALL IT <---
            # Compute Chapter 5 specific metrics (Extraction Yield, R_ID, D_ID, U_cost, ETR)
            metrics = compute_metrics(summary_dict)
            summary_dict.update(metrics)

            per_browser_summaries[config] = summary_dict

    # 4. Statistical Significance Testing (Output 2)
    print("\n--- STATISTICAL SIGNIFICANCE TESTS (Within-Browser & Across-Browser) ---")
    stats_report_lines = []
    
    for config, s in per_browser_summaries.items():
        pre = s["pre_bids"]
        post = s["post_bids"]
        
        if len(pre) >= 10 and not np.all(np.array(pre) == np.array(post)):
            # Wilcoxon Signed-Rank Test (paired pre vs post bids)
            stat, p_val = stats.wilcoxon(pre, post, zero_method="wilcox")
            p_str = f"{p_val:.4e}" if p_val < 0.001 else f"{p_val:.4f}"
            sig = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else "n.s."))
            line = f"{config:<20} | Wilcoxon W = {stat:8.1f} | p = {p_str:<10} | Sig: {sig}"
            s["wilcoxon_p"] = p_str
            s["wilcoxon_sig"] = sig
        else:
            line = f"{config:<20} | Insufficient variance or sample size for Wilcoxon test."
            s["wilcoxon_p"] = "N/A"
            s["wilcoxon_sig"] = "n.s."
            
        print(line)
        stats_report_lines.append(line)

    # Kruskal-Wallis across all configurations with delta samples
    valid_groups = [s["all_deltas"] for s in per_browser_summaries.values() if len(s["all_deltas"]) >= 5]
    if len(valid_groups) >= 2:
        kw_stat, kw_pval = stats.kruskal(*valid_groups)
        kw_line = f"\nKruskal-Wallis Test (Across Browser Delta Distributions): H = {kw_stat:.3f}, p = {kw_pval:.4e}"
        print(kw_line)
        stats_report_lines.append(kw_line)

    # 5. Output 1: Master Thesis Summary Table (Direct match to Chapter 5)
    summary_path = OUTPUT_DIR / "thesis_summary_table.csv"
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Browser Configuration",
            "Yield (%)",               # Section 5.1.2
            "Analyzed Sites",
            "Active Auctions",
            "R_ID (Re-ID Rate)",       # Section 5.2.1
            "D_ID (Diffusion)",        # Section 5.2.2
            "U_cost (Breakage)",       # Section 5.3.1
            "High Resistance (%)",
            "Low/Tracked (%)",
            "Median CPM Delta (%)",
            "ETR Metric Score",        # Section 5.3.1 Composite Metric
            "Wilcoxon p-value",
            "Significance"
        ])
        for config in CONFIGS:
            if config in per_browser_summaries:
                b = per_browser_summaries[config]
                writer.writerow([
                    config,
                    f"{b['extraction_yield']}%",
                    b["total_sites"],
                    b["active_auction_sites"],
                    b["r_id"],
                    b["d_id"],
                    b["u_cost"],
                    f"{b['high_res_pct']}%",
                    f"{b['low_res_pct']}%",
                    f"{b['median_cpm_delta']}%",
                    b["etr_score"],
                    b.get("wilcoxon_p", "N/A"),
                    b.get("wilcoxon_sig", "n.s.")
                ])

    # 6. Save text summary report
    with open(OUTPUT_DIR / "statistical_report.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(stats_report_lines))

    print("\n==========================================================")
    print(f"[!] Evaluation Complete. Artifacts saved in: {OUTPUT_DIR.resolve()}/")
    print("    - thesis_summary_table.csv   <-- Master table for Results chapter")
    print("    - statistical_report.txt     <-- p-values for Statistical Rigour")
    print("    - master_<browser>.csv       <-- Full per-domain breakdowns")
    print("==========================================================\n")

if __name__ == "__main__":
    run_analysis()