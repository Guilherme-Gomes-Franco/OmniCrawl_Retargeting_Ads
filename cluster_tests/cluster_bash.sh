#!/bin/bash

declare -a experiments=(
    "chrome baseline" 
    "firefox baseline" 
    "firefox hardened" 
    "brave baseline" 
    "brave hardened"
)

for exp in "${experiments[@]}"; do
    read -r BROWSER MODE <<< "$exp"
    
    if [ "$MODE" == "hardened" ]; then
        FLAG="--hardened"
    else
        FLAG=""
    fi

    JOB_NAME="ETR_${BROWSER}_${MODE}"
    
    echo "[*] Submitting $JOB_NAME to OAR..."
    
    # We pass the Browser and Flag as arguments to our wrapper script
    # This is much cleaner and won't crash the OAR parser
    oarsub -t docker-swarm \
           -n "$JOB_NAME" \
           -p "host in ('bulbasaur-2','kadabra-08','kadabra-01')"  \
           -l nodes=1,walltime=10:00:00 \
           "./job_wrapper.sh $BROWSER $FLAG"
done