
BROWSER="brave"
FLAG=""

JOB_NAME="ETR_${BROWSER}_hardened"
    
echo "[*] Submitting $JOB_NAME to OAR..."



# --- OAR SUBMISSION ---
oarsub -t docker-swarm \
           -n "$JOB_NAME" \
           -p "host in ('kadabra-08')"  \
           -l nodes=1,walltime=10:00:00 \
           "./job_wrapper.sh $BROWSER $FLAG"