
BROWSER="brave"
FLAG="--hardened"

JOB_NAME="ETR_${BROWSER}_hardened"
    
echo "[*] Submitting $JOB_NAME to OAR..."



# --- OAR SUBMISSION ---
oarsub -t docker-swarm \
           -n "$JOB_NAME" \
           -p "host in ('psyduck-1', 'psyduck-2', 'squirtle-3', 'squirtle-4', 'charmander-4', 'charmander-5')"  \
           -l nodes=1,walltime=10:00:00 \
           "./job_wrapper.sh $BROWSER $FLAG"