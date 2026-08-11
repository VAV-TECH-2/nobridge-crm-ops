#!/usr/bin/env bash
# Deploy the Pipeline Autopilot to the CRM VM. Idempotent; safe to re-run.
#
#   ./deploy-autopilot.sh              # copy code, install units, leave the timer as it is
#   ./deploy-autopilot.sh --enable     # ...and enable + start the hourly timer
#   ./deploy-autopilot.sh --dry-once   # ...and run one DRY pass on the VM, writing nothing
#
# Run from a Git Bash shell on Windows, never PowerShell (a UTF-8 BOM corrupts scripts piped over
# SSH; see the CRM README). Modelled on blocklist-guard/deploy-blocklist-guard.sh.
set -euo pipefail

VM="${VM:-azureuser@20.189.126.94}"
DEST=/opt/nobridge-pipeline-autopilot
HERE="$(cd "$(dirname "$0")" && pwd)"

PY_FILES=(autopilot.py judge.py rules.py evidence.py crm.py db.py spec.py bizdays.py
          store.py preflight.py revert.py twclient.py)

echo "== copying to $VM:$DEST"
ssh -o StrictHostKeyChecking=no "$VM" "sudo mkdir -p $DEST/data && sudo chown -R azureuser:azureuser $DEST"
for f in "${PY_FILES[@]}"; do
  [ -f "$HERE/$f" ] || { echo "   MISSING $f"; exit 1; }
  scp -q "$HERE/$f" "$VM:$DEST/$f"
  echo "   $f"
done
scp -q "$HERE/pipeline-autopilot.service" "$HERE/pipeline-autopilot.timer" "$VM:/tmp/"

echo "== installing units"
ssh "$VM" '
  set -e
  sudo install -m 644 /tmp/pipeline-autopilot.service /etc/systemd/system/pipeline-autopilot.service
  sudo install -m 644 /tmp/pipeline-autopilot.timer   /etc/systemd/system/pipeline-autopilot.timer
  rm -f /tmp/pipeline-autopilot.service /tmp/pipeline-autopilot.timer
  sudo systemctl daemon-reload
  touch /home/azureuser/pipeline-autopilot.log
'

echo "== preflight on the VM (read-only)"
ssh "$VM" "cd $DEST && AUTOPILOT_SPEC_DIR=/opt/heydeal-automations-dashboard python3 preflight.py" \
  || { echo "   PREFLIGHT FAILED - not enabling anything"; exit 1; }

for arg in "$@"; do
  case "$arg" in
    --dry-once)
      echo "== one DRY run on the VM (writes nothing)"
      ssh "$VM" "cd $DEST && AUTOPILOT_SPEC_DIR=/opt/heydeal-automations-dashboard \
                 AUTOPILOT_DB=$DEST/data/autopilot.db python3 autopilot.py 2>&1 | tail -25"
      ;;
    --enable)
      echo "== enabling the hourly timer"
      ssh "$VM" 'sudo systemctl enable --now pipeline-autopilot.timer &&
                 systemctl list-timers pipeline-autopilot.timer --no-pager'
      ;;
  esac
done

echo "== done"
echo "   logs:    ssh $VM 'tail -50 /home/azureuser/pipeline-autopilot.log'"
echo "   journal: ssh $VM 'sudo journalctl -u pipeline-autopilot -n 80 --no-pager'"
echo "   run now: ssh $VM 'sudo systemctl start pipeline-autopilot'"
