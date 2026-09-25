import sqlite3, zlib, json, glob
from urllib.parse import urlparse

configs = ["chrome_baseline", "firefox_baseline", "firefox_hardened", "brave_baseline", "brave_hardened"]

print(f"{'Configuration':<20} | {'Unique Tracking Entities (Hosts)':<35}")
print("-" * 60)

for c in configs:
    unique_hosts = set()
    for db in glob.glob(f"ETR_data/{c}_*.log.sqlite3"):
        conn = sqlite3.connect(db)
        for _, _, _, data in conn.cursor().execute("SELECT browser, alexa_url, timeout, data FROM crawl"):
            try:
                payload = json.loads(zlib.decompress(data).decode('utf-8', 'ignore'))
                for req in payload.get("requests", []):
                    etr = req.get("etr_metrics", {})
                    # Only count hosts that actually received a sync or a UID
                    if etr.get("is_csync") or etr.get("smuggled_uids"):
                        host = req.get("host") or urlparse(req.get("url", "")).netloc
                        if host:
                            unique_hosts.add(host)
            except Exception:
                pass
        conn.close()
    print(f"{c:<20} | {len(unique_hosts):<35}")