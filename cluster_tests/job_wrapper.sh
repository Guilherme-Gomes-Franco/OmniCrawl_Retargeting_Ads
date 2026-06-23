#!/bin/bash
# ---------------------------------------------------------
# This script runs ON THE WORKER NODE
# ---------------------------------------------------------

# 1. Capture arguments passed from OAR
export BROWSER=$1
export HARDENED=$2

# 2. DYNAMICALLY FIND THE PROJECT ROOT
# Get the directory where THIS script (job_wrapper.sh) is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# Go UP one level to the project root (where Dockerfile lives)
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

cd "$PROJECT_ROOT"

echo "[*] Cleaning up lingering processes and containers..."
# Kill any mitmdump or Xvfb processes left over on this node from previous runs
pkill -9 mitmdump || true
pkill -9 Xvfb || true

echo "[*] Starting job on node: $(hostname)"
echo "[*] Browser: $BROWSER | Flag: $HARDENED"

echo "[*] Cleaning up old container states..."
docker compose down --remove-orphans

# 3. Build the image locally on this specific node
# This fixes the 'ContainerConfig' error by matching the local Docker version
echo "[*] Building Docker image..."
docker build -t omnicrawl-worker .

# 4. Launch the workers via Compose
# We use the environment variables we exported above
echo "[*] Launching Docker Compose..."
docker compose up --abort-on-container-exit