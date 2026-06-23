#!/bin/bash

declare -a experiments=(
    "chrome baseline"
    "webkit baseline"
    "brave baseline"
    "brave hardened"
    "firefox baseline"
    "firefox hardened" 
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
           -p "host in ('psyduck-1', 'squirtle-3', 'squirtle-4', 'charmander-3', 'charmander-4','charmander-5')"  \
           -l nodes=1,walltime=10:00:00 \
           "./job_wrapper.sh $BROWSER $FLAG"
done