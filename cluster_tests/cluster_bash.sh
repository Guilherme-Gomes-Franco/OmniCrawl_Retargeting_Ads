#!/bin/bash

# Configuration Matrix: [Browser] [Mode]
declare -a experiments=(
    "chrome baseline"
    "webkit baseline"
    "brave baseline"
    "brave hardened"
    "firefox baseline"
    "firefox hardened"
)

# Get the current directory path to pass to the worker nodes
PROJECT_DIR=$(pwd)

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
    
    # --- THE COMMAND STRING ---
    # 1. Navigate to the project folder on the node
    # 2. Build the image locally on the node
    # 3. Launch the 2 workers defined in your docker-compose.yml
    COMMAND="cd $PROJECT_DIR && docker build -t omnicrawl-worker . && BROWSER=$BROWSER HARDENED=$HARDENED docker-compose up --abort-on-container-exit"

    # --- OAR SUBMISSION ---
    oarsub -t docker-swarm \
           -n "$JOB_NAME" \
           -p "host in ('squirtle-1', 'squirtle-2', 'squirtle-3', 'squirtle-4', 'charmander-3', 'charmander-4')"  \
           -l nodes=1,walltime=10:00:00 \
           "$COMMAND"
done

echo "----------------------------------------------------------"
echo "All 6 experiments submitted! Total 12 workers starting."
echo "Use 'oarstat -u $(whoami)' to monitor progress."
echo "Check data/heartbeat_<browser>.csv for live site logs."
echo "----------------------------------------------------------"