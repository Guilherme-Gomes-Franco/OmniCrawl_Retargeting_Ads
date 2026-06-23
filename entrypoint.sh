#!/bin/bash
# We keep set -e to catch errors, but we will "guard" the commands that might fail
set -e
set -u

# Use variables from OAR/Docker-Compose environment
BROWSER=${BROWSER:-chrome}
HARDENED_FLAG=${HARDENED:-""}
PROXY_PORT=${PROXY_PORT:-38080}
DISPLAY_NUM=${DISPLAY_NUM:-99}

# 1. Start the Virtual Display (Xvfb)
export DISPLAY=:$DISPLAY_NUM
echo "[*] Cleaning up old Xvfb locks for $DISPLAY..."
# If a previous job crashed on this node, the lock file prevents Xvfb from starting.
# We remove it to prevent the "Aborting" error.
rm -f /tmp/.X${DISPLAY_NUM}-lock || true

echo "[*] Starting Xvfb..."
Xvfb :$DISPLAY_NUM -screen 0 1920x1080x24 -ac +extension RANDR &
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
cleanup() {
    # Stop other workers from triggering cleanup if we are already cleaning up
    trap - EXIT 
    echo "[*] Cleanup triggered. Migrating data to NFS..."
    mv -f /tmp/${RUN_ID}* /app/data/ 2>/dev/null || true
    mv -f /app/heartbeat_*.csv /app/data/ 2>/dev/null || true
    [ -n "${PROXY_PID:-}" ] && kill $PROXY_PID 2>/dev/null || true
    exit
}
trap cleanup EXIT SIGTERM ERR

# 4. Certificates and NSS setup
echo "[*] Generating proxy certificates..."
mkdir -p /root/.mitmproxy

# Run mitmdump just long enough to generate files, then stop
# We use a different port (38999) just for the generator
timeout 5 mitmdump --listen-port 38999 > /dev/null 2>&1 || true

# Check if the cert was created
if [ ! -f "/root/.mitmproxy/mitmproxy-ca-cert.pem" ]; then
    echo "[!] Cert not found, trying one more time..."
    mitmdump --version > /dev/null 2>&1 || true
fi

if [ -f "/root/.mitmproxy/mitmproxy-ca-cert.pem" ]; then
    echo "[+] Cert found! Installing to OS..."
    cp /root/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy-ca-cert.crt
    update-ca-certificates
else
    echo "[!] FATAL ERROR: mitmproxy failed to generate certificates."
    ls -la /root/
    exit 1
fi

echo "[*] Installing to Chromium NSS DB..."
mkdir -p /root/.pki/nssdb
echo "" > /tmp/nss_pwd.txt
certutil -d sql:/root/.pki/nssdb -N -f /tmp/nss_pwd.txt || true
certutil -A -n "mitmproxy" -t "TC,," -i /root/.mitmproxy/mitmproxy-ca-cert.pem -d sql:/root/.pki/nssdb -f /tmp/nss_pwd.txt || true

# 5. Start the proxy
echo "[*] Starting mitmproxy on port $PROXY_PORT..."
# removed > /dev/null so that if mitmproxy fails, 
# I will see the error in the OAR log
PYTHONPATH=./scripts mitmdump -s "proxy/injector.py" \
  --set block_global=false \
  --set js_filepath="scripts/stealth.js" \
  --set timeout_msec=90000 \
  --set log_filepath="$LOG_DB" \
  --set dump_filepath="$DUMP_DB" \
  --listen-host 127.0.0.1 \
  --listen-port $PROXY_PORT \
  --anticache \
  --no-http2 &
PROXY_PID=$!

sleep 5 # Wait for proxy to bind

# 6. Run the Causal Orchestrator
echo "[*] Launching Causal Orchestrator..."
# We add -u to python3 to make sure logs appear in the cluster console immediately
if [ -n "$BIN_PATH" ]; then
    python3 -u scripts/orchestration.py \
    --browser "$BROWSER" \
    --binary "$BIN_PATH" \
    $HARDENED_FLAG \
    --proxy-port "$PROXY_PORT" \
    --start-idx "${START_IDX:-0}" \
    --end-idx "${END_IDX:-150}"
else
    python3 -u scripts/orchestration.py \
    --browser "$BROWSER" \
    $HARDENED_FLAG \
    --proxy-port "$PROXY_PORT" \
    --start-idx "${START_IDX:-0}" \
    --end-idx "${END_IDX:-150}"
fi

# The cleanup trap handles the 'mv' and 'kill' automatically
exit 0