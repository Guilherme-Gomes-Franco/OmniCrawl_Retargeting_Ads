#!/bin/bash

declare -a experiments=(
    "brave baseline" ,
    "brave hardened" ,
    "firefox baseline" ,
    "firefox hardened" ,
    "chrome baseline"
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
           -p "host in ('squirtle-1','squirtle-3', 'bulbasaur-4')"  \
           -l nodes=1,walltime=10:00:00 \
           "./job_wrapper.sh $BROWSER $FLAG"
done