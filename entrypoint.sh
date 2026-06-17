#!/bin/bash
set -e

# Use variables from OAR/Docker-Compose environment
BROWSER=${BROWSER:-chrome}
HARDENED_FLAG=${HARDENED:-""}

# NEW: Use variables from Docker Compose
PROXY_PORT=${PROXY_PORT:-38080}
DISPLAY_NUM=${DISPLAY_NUM:-99}

# 1. Start the Virtual Display (Xvfb)
export DISPLAY=:$DISPLAY_NUM
Xvfb :$DISPLAY_NUM -screen 0 1920x1080x24 &
sleep 2

# 2. Define Binary Paths (Only override for Brave)
if [ "$BROWSER" == "brave" ]; then
    BIN_PATH="/usr/bin/brave-browser"
else
    BIN_PATH=""
fi

# 3. Create a unique identifier
RUN_ID="${BROWSER}_${PROXY_PORT}_$(date +%s)_$RANDOM"
LOG_DB="/tmp/${RUN_ID}.log.sqlite3"
DUMP_DB="/tmp/${RUN_ID}.dump.sqlite3"

echo "[*] Container initialized. Run ID: $RUN_ID"
echo "[*] Configuration: Browser=$BROWSER, Hardened=$HARDENED_FLAG"

# DATA MIGRATION TRAP
# This function runs even if Python crashes or OAR kills the job
cleanup() {
    echo "[*] Signal received or script ending. Migrating data to NFS..."
    # Move SQLite databases
    mv -f /tmp/${RUN_ID}* /app/data/ 2>/dev/null || true
    # Move heartbeat logs
    mv -f /app/heartbeat_${BROWSER}.csv /app/data/ 2>/dev/null || true
    
    if [ -n "${PROXY_PID:-}" ]; then
        kill $PROXY_PID 2>/dev/null || true
    fi
    echo "[*] Cleanup complete. Exiting."
}
# Catch SIGTERM (Cluster timeout), SIGINT (Ctrl+C), and ERR (Python crash)
trap cleanup EXIT SIGTERM SIGINT ERR


echo "[*] Generating proxy certificates..."
mitmdump > /dev/null 2>&1 &
MITM_PID=$!
sleep 3
kill $MITM_PID
sleep 1

echo "[*] Installing mitmproxy certificate to Ubuntu OS..."
cp /root/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy-ca-cert.crt
update-ca-certificates

echo "[*] Installing mitmproxy certificate to Chromium NSS DB..."
mkdir -p $HOME/.pki/nssdb
certutil -d sql:$HOME/.pki/nssdb -N --empty-password
certutil -A -n "mitmproxy" -t "TC,," -i /root/.mitmproxy/mitmproxy-ca-cert.pem -d sql:$HOME/.pki/nssdb

# Start the proxy
PYTHONPATH=./scripts mitmdump -s "proxy/injector.py" \
  --set block_global=false \
  --set js_filepath="scripts/stealth.js" \
  --set timeout_msec=90000 \
  --set log_filepath="$LOG_DB" \
  --set dump_filepath="$DUMP_DB" \
  --listen-host 127.0.0.1 \
  --listen-port $PROXY_PORT \
  --anticache \
  --no-http2 > /dev/null 2>&1 &
PROXY_PID=$!

sleep 5 # Wait for proxy to bind

# 5. Run the Causal Orchestrator
echo "[*] Launching Causal Orchestrator..."
if [ -n "$BIN_PATH" ]; then
    python3 scripts/orchestration.py \
    --browser "$BROWSER" \
    --binary "$BIN_PATH" \
    $HARDENED_FLAG \
    --proxy-port "$PROXY_PORT" \
    --start-idx "${START_IDX:-0}" \
    --end-idx "${END_IDX:-150}"
else
    python3 scripts/orchestration.py \
    --browser "$BROWSER" \
    $HARDENED_FLAG \
    --proxy-port "$PROXY_PORT" \
    --start-idx "${START_IDX:-0}" \
    --end-idx "${END_IDX:-150}"
fi

# 6. SHUTDOWN & DATA MIGRATION
echo "[*] Moving database from local container storage to NFS..."
mv "$LOG_DB" /app/data/
mv "$DUMP_DB" /app/data/

echo "[*] Crawl finished. Shutting down."
kill $PROXY_PID
exit 0