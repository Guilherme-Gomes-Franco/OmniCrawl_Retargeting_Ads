#!/usr/bin/env python3
import sqlite3
import zlib
import json
import csv
from pathlib import Path

# Paths to your database files
log_db = Path("data/chrome_baseline.log.sqlite3")
dump_db = Path("data/chrome_baseline.dump.sqlite3")
out_dir = Path("output")
out_dir.mkdir(exist_ok=True)

def decompress_json(blob):
    try:
        raw = zlib.decompress(blob)
        return json.loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return None

def export_log_db():
    conn = sqlite3.connect(log_db)
    cur = conn.cursor()
    rows = []
    # Query main crawl table
    for browser, alexa_url, timeout, data in cur.execute(
        "SELECT browser, alexa_url, timeout, data FROM crawl"
    ):
        obj = decompress_json(data)
        rows.append({
            "browser": browser,
            "alexa_url": alexa_url,
            "timeout": timeout,
            "requests_count": len(obj.get("requests", [])) if obj else "",
            "frames_count": len(obj.get("frames", [])) if obj else "",
            "payload_json": json.dumps(obj, ensure_ascii=False) if obj else "",
        })
    conn.close()

    csv_path = out_dir / "chrome_baseline_log_decompressed.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["browser", "alexa_url", "timeout", "requests_count", "frames_count", "payload_json"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path

# --- NEW FUNCTION FOR JS EXCEPTIONS (SITE BREAKAGE) ---
def export_js_exceptions():
    conn = sqlite3.connect(log_db)
    cur = conn.cursor()
    
    # We check if the table exists first to avoid crashes on old DBs
    cur.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='js_exceptions'")
    if cur.fetchone()[0] == 0:
        print("[!] No js_exceptions table found in this database.")
        conn.close()
        return None

    rows = []
    # Select everything from our new exceptions table
    for row_id, browser, url, message, stack, fingerprint in cur.execute(
        "SELECT id, browser, url, message, stack, fingerprint FROM js_exceptions"
    ):
        rows.append({
            "id": row_id,
            "browser": browser,
            "url": url,
            "message": message,
            "stack_trace": stack,
            "fingerprint": fingerprint
        })
    conn.close()

    csv_path = out_dir / "chrome_baseline_js_exceptions.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "browser", "url", "message", "stack_trace", "fingerprint"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path

def export_dump_db():
    # ... (Your existing dump_db code is fine and remains the same)
    conn = sqlite3.connect(dump_db)
    cur = conn.cursor()
    content_map = {}
    for md5, data in cur.execute("SELECT md5, data FROM content"):
        try: content_map[md5] = zlib.decompress(data).decode("utf-8", "ignore")
        except: content_map[md5] = ""
    rows = []
    for uid, md5 in cur.execute("SELECT uid, md5 FROM uid2md5"):
        rows.append({"uid": uid, "md5": md5, "content_preview": content_map.get(md5, "")[:500]})
    conn.close()
    csv_path = out_dir / "chrome_baseline_dump_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["uid", "md5", "content_preview"])
        writer.writeheader()
        writer.writerows(rows)
    return csv_path

if __name__ == "__main__":
    print(f"Exported Logs: {export_log_db()}")
    
    # Run the new exception exporter
    exception_file = export_js_exceptions()
    if exception_file:
        print(f"Exported JS Exceptions: {exception_file}")
        
    print(f"Exported Dump Index: {export_dump_db()}")