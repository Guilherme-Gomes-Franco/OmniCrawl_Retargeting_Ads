#!/usr/bin/env python3
import sqlite3
import zlib
import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python unpack.py data/run_TIMESTAMP_chrome/log.sqlite3")
    sys.exit(1)

log_db = Path(sys.argv[1])

def analyze_etr_metrics(path):
    conn = sqlite3.connect(path)
    print(f"\n========================================================")
    print(f"   THESIS ETR METRICS ANALYSIS: {path.name}")
    print(f"========================================================\n")

    cur = conn.cursor()
    
    # Fetch all rows to analyze the full causal inference crawl
    for row in cur.execute("SELECT browser, alexa_url, timeout, data FROM crawl"):
        browser_phase = row[0]
        url = row[1]
        timeout = row[2]
        
        try:
            # Decompress the OmniCrawl binary blob into JSON
            raw_json = zlib.decompress(row[3]).decode("utf-8", "ignore")
            obj = json.loads(raw_json)
        except Exception as e:
            print(f"Error decompressing data for {url}: {e}")
            continue
            
        timeout_str = "[TIMEOUT]" if timeout else "[CLEAN STOP]"
        print(f"[{browser_phase}] -> {url} {timeout_str}")
        
        found_rtb = False
        found_csync = False
        
        requests = obj.get('requests',[])
        for req in requests:
            etr = req.get('etr_metrics', {})
            
            # 1. Silo 1: Check RTB / CPM Values
            if etr.get('is_rtb') or etr.get('cpm_values'):
                found_rtb = True
                req_url = req.get('url', '')
                short_url = req_url[:75] + "..." if len(req_url) > 75 else req_url
                print(f"  [+] RTB Auction | {short_url}")
                print(f"      -> CPM Bids: {etr.get('cpm_values')}")
            
            # 2. Silo 2: Check UID Smuggling & CSync
            if etr.get('is_csync') or etr.get('smuggled_uids'):
                found_csync = True
                req_url = req.get('url', '')
                short_url = req_url[:75] + "..." if len(req_url) > 75 else req_url
                
                if etr.get('is_csync'):
                    print(f"  [!] CSync Event | {short_url}")
                if etr.get('smuggled_uids'):
                    print(f"  [!] UID Smuggled | {etr.get('smuggled_uids')} | {short_url}")
        
        if not found_rtb and not found_csync:
            print("  [-] No RTB or tracking metrics found in this phase.")
        print("-" * 60)

    conn.close()

if __name__ == "__main__":
    if log_db.exists():
        analyze_etr_metrics(log_db)
    else:
        print(f"[Error] Database not found at {log_db}")