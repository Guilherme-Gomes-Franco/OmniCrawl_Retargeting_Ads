#!/bin/bash

BROWSER="firefox"
FLAG="--hardened"
JOB_NAME="ETR_${BROWSER}_hardened"

echo "[*] Submitting $JOB_NAME as a BESTEFFORT job to OAR..."

# --- OAR SUBMISSION ---
# Notice we pass BOTH -t docker-swarm and -t besteffort
oarsub -t docker-swarm \
       -t besteffort \
       -n "$JOB_NAME" \
       -p "host in ('moltres-01', 'moltres-02')" \
       -l nodes=1,walltime=10:00:00 \
       "./job_wrapper.sh $BROWSER $FLAG"