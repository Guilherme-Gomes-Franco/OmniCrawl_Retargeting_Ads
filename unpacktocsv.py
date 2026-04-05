#!/usr/bin/env python3
import sqlite3
import zlib
import json
import csv
from pathlib import Path

log_db = Path("data/pilot.log.sqlite3")
dump_db = Path("data/pilot.dump.sqlite3")
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

    csv_path = out_dir / "pilot_log_decompressed.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["browser", "alexa_url", "timeout", "requests_count", "frames_count", "payload_json"],
        )
        writer.writeheader()
        writer.writerows(rows)

    return csv_path

def export_dump_db():
    conn = sqlite3.connect(dump_db)
    cur = conn.cursor()

    content_map = {}
    for md5, data in cur.execute("SELECT md5, data FROM content"):
        try:
            content_map[md5] = zlib.decompress(data).decode("utf-8", "ignore")
        except Exception:
            content_map[md5] = ""

    rows = []
    for uid, md5 in cur.execute("SELECT uid, md5 FROM uid2md5"):
        rows.append({
            "uid": uid,
            "md5": md5,
            "content_preview": content_map.get(md5, "")[:500],
        })

    conn.close()

    csv_path = out_dir / "pilot_dump_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["uid", "md5", "content_preview"],
        )
        writer.writeheader()
        writer.writerows(rows)

    return csv_path

if __name__ == "__main__":
    print(export_log_db())
    print(export_dump_db())
