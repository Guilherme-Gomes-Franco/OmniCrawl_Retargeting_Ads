#!/usr/bin/env python3
import argparse
import subprocess
import os
import sys

def main():
    parser = argparse.ArgumentParser(description="Launch mitmproxy for OmniCrawl ETR measurement.")
    parser.add_argument(
        "run_name", 
        help="Name of the run (e.g., chrome_baseline, firefox_rfp). "
             "This will name the databases in the data/ folder."
    )
    args = parser.parse_args()

    # Automatically format the database output paths
    log_file = f"./data/{args.run_name}.log.sqlite3"
    dump_file = f"./data/{args.run_name}.dump.sqlite3"

    print(f"[*] Starting proxy for run: {args.run_name}")
    print(f"[*] Log DB:  {log_file}")
    print(f"[*] Dump DB: {dump_file}")
    print("[*] Press Ctrl+C to stop the proxy.")

    # Construct the mitmdump command
    cmd =[
        "mitmdump",
        "-s", "proxy/injector.py",
        "--set", "block_global=false",
        "--set", "js_filepath=scripts/stealth.js",
        "--set", "timeout_msec=90000",
        "--set", f"log_filepath={log_file}",
        "--set", f"dump_filepath={dump_file}",
        "--listen-host", "127.0.0.1",
        "--listen-port", "38080",
        "--anticache",
        "--no-http2"
    ]

    # Inject PYTHONPATH so injector.py can find scripts/sqlitedb.py
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"./scripts:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = "./scripts"

    try:
        # Execute the proxy process
        subprocess.run(cmd, env=env)
    except KeyboardInterrupt:
        print("\n[*] Proxy stopped by user.")
    except Exception as e:
        print(f"\n[!] Fatal error starting proxy: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()