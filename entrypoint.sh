#!/bin/bash
set -e

BROWSER=$1
HARDENED_FLAG=$2

if [ -z "$BROWSER" ]; then
  echo "[!] No browser specified. Defaulting to chrome."
  BROWSER="chrome"
fi

# 1. Start the Virtual Display (Xvfb)
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 &
sleep 2

# 2. Define Binary Paths (Only override for Brave)
if [ "$BROWSER" == "brave" ]; then
    BIN_PATH="/usr/bin/brave-browser"
else
    BIN_PATH=""
fi

# 3. Create a unique identifier
RUN_ID="${BROWSER}_$(date +%s)_$RANDOM"
LOG_DB="/app/data/${RUN_ID}.log.sqlite3"
DUMP_DB="/app/data/${RUN_ID}.dump.sqlite3"

echo "[*] Container initialized. Run ID: $RUN_ID"

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
  --listen-port 38080 \
  --anticache \
  --no-http2 > /dev/null 2>&1 &
PROXY_PID=$!

sleep 3 # Wait for proxy to bind

# 5. Run the Causal Orchestrator
echo "[*] Launching Causal Orchestrator..."
if [ -n "$BIN_PATH" ]; then
    python3 scripts/orchestration.py --browser "$BROWSER" --binary "$BIN_PATH" $HARDENED_FLAG
else
    python3 scripts/orchestration.py --browser "$BROWSER" $HARDENED_FLAG
fi

echo "[*] Crawl finished. Shutting down."
kill $PROXY_PID
exit 0