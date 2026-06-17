#!/bin/bash

# Configuration Matrix: [Browser] [Mode] [Hardened_Flag]
# 1. Chrome (Baseline)
# 2. WebKit (ITP Baseline)
# 3. Brave Default
# 4. Brave Shields (Strict)
# 5. Firefox Default
# 6. Firefox RFP (Hardened)

declare -a experiments=(
    "chrome baseline"
    "webkit baseline"
    "brave baseline"
    "brave hardened"
    "firefox baseline"
    "firefox hardened"
)

# Divide 150 sites into batches of 30
BATCH_SIZE=30
TOTAL_SITES=150

for exp in "${experiments[@]}"; do
    read -r BROWSER MODE <<< "$exp"
    
    # Set the flag for orchestration.py
    if [ "$MODE" == "hardened" ]; then
        HARDENED="--hardened"
    else
        HARDENED=""
    fi

    JOB_NAME="ETR_${BROWSER}_${MODE}"
    
    echo "[*] Submitting $JOB_NAME to OAR..."
    
    # -t docker-swarm: Enables Docker
    # -l nodes=1,walltime=15:00:00: Requests 1 node for 15 hours
    # Pass environment variables to the OAR environment
    oarsub -t docker-swarm \
           -n "$JOB_NAME" \
           -l nodes=1,walltime=15:00:00 \
           "BROWSER=$BROWSER HARDENED=$HARDENED docker-compose up --abort-on-container-exit"
done