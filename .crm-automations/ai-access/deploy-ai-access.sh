#!/usr/bin/env bash
# Deploy the AI Access connector to the CRM VM. Idempotent; safe to re-run.
#
#   ./deploy-ai-access.sh              # copy code, install the unit, restart if already running
#   ./deploy-ai-access.sh --enable     # ...and enable + start it
#   ./deploy-ai-access.sh --check      # ...and run selfcheck on the VM, changing nothing
#
# Run from a Git Bash shell on Windows, never PowerShell (a UTF-8 BOM corrupts scripts piped over
# SSH; see the CRM README). Modelled on pipeline-autopilot/deploy-autopilot.sh.
#
# It does NOT copy the autopilot's modules or workflow_spec.py. Those are deployed by their own
# scripts and imported at runtime — one CRM client, one validator, one ruleset. If the autopilot is
# not deployed, this service will not start, and selfcheck says so.
set -euo pipefail

VM="${VM:-azureuser@20.189.126.94}"
DEST=/opt/nobridge-ai-access
AUTOPILOT=/opt/nobridge-pipeline-autopilot
HERE="$(cd "$(dirname "$0")" && pwd)"

PY_FILES=(server.py tools.py context.py guard.py auth.py tokens.py store_ai.py openapi.py
          selfcheck.py cli.py deps.py)

echo "== checking the VM has what this imports"
ssh -o StrictHostKeyChecking=no "$VM" "test -f $AUTOPILOT/crm.py" \
  || { echo "   $AUTOPILOT/crm.py is missing - deploy pipeline-autopilot first"; exit 1; }
ssh "$VM" "test -f /opt/heydeal-automations-dashboard/workflow_spec.py" \
  || { echo "   the dashboard's workflow_spec.py is missing - deploy the dashboard first"; exit 1; }

echo "== local selfcheck before copying anything"
( cd "$HERE" && AUTOPILOT_FORCE_REMOTE=1 python3 selfcheck.py >/dev/null ) \
  || { echo "   LOCAL SELFCHECK FAILED - fix it before deploying"; exit 1; }

echo "== copying to $VM:$DEST"
ssh "$VM" "sudo mkdir -p $DEST/data && sudo chown -R azureuser:azureuser $DEST"
for f in "${PY_FILES[@]}"; do
  [ -f "$HERE/$f" ] || { echo "   MISSING $f"; exit 1; }
  scp -q "$HERE/$f" "$VM:$DEST/$f"
  echo "   $f"
done
scp -q "$HERE/nobridge-ai-access.service" "$VM:/tmp/"

echo "== installing the unit"
ssh "$VM" '
  set -e
  sudo install -m 644 /tmp/nobridge-ai-access.service \
       /etc/systemd/system/nobridge-ai-access.service
  rm -f /tmp/nobridge-ai-access.service
  sudo systemctl daemon-reload
  # The token database is a secret: only root reads it.
  sudo chmod 700 /opt/nobridge-ai-access/data 2>/dev/null || true
'

echo "== selfcheck on the VM (read-only)"
ssh "$VM" "cd $DEST && sudo AI_AUTOPILOT_DIR=$AUTOPILOT \
           AUTOPILOT_SPEC_DIR=/opt/heydeal-automations-dashboard \
           AI_ACCESS_DB=$DEST/data/aiaccess.db python3 selfcheck.py" \
  || { echo "   SELFCHECK FAILED ON THE VM - not starting anything"; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --enable)
      echo "== enabling and starting"
      ssh "$VM" 'sudo systemctl enable --now nobridge-ai-access &&
                 sleep 3 && systemctl status nobridge-ai-access --no-pager | head -12'
      ;;
    --check) ;;   # the selfcheck above is the whole job
  esac
done

# A restart is only right if it was already running; --enable handles the first start.
if ssh "$VM" 'systemctl is-active --quiet nobridge-ai-access'; then
  echo "== restarting (it was already running)"
  ssh "$VM" 'sudo systemctl restart nobridge-ai-access && sleep 3 &&
             curl -sf localhost:3300/healthz && echo'
fi

echo "== done"
echo "   issue a token:  ssh $VM 'cd $DEST && sudo python3 tokens.py --issue <email> --scope write'"
echo "   list tokens:    ssh $VM 'cd $DEST && sudo python3 tokens.py --list'"
echo "   journal:        ssh $VM 'sudo journalctl -u nobridge-ai-access -n 80 --no-pager'"
echo "   health:         ssh $VM 'curl -s localhost:3300/healthz'"
