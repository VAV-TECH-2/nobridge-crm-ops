#!/usr/bin/env bash
# Deploy/refresh the blocklist-guard automation on the CRM VM.
# Usage: bash deploy-blocklist-guard.sh   (from this directory, workstation side)
set -euo pipefail
VM="azureuser@20.189.126.94"
DIR="$(cd "$(dirname "$0")" && pwd)"

scp -o StrictHostKeyChecking=no \
  "$DIR/guard.py" "$DIR/blocklist-guard.service" "$DIR/blocklist-guard.timer" \
  "$DIR/register_blocklist_guard.py" "$VM:/tmp/"

ssh -o StrictHostKeyChecking=no "$VM" '
  set -euo pipefail
  sudo mkdir -p /opt/heydeal-blocklist-guard
  sudo mv /tmp/guard.py /tmp/register_blocklist_guard.py /opt/heydeal-blocklist-guard/
  sudo mv /tmp/blocklist-guard.service /tmp/blocklist-guard.timer /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now blocklist-guard.timer
  sudo python3 /opt/heydeal-blocklist-guard/register_blocklist_guard.py
  sudo systemctl start blocklist-guard.service --no-block
  echo "deployed; timer:"; systemctl list-timers blocklist-guard.timer --no-pager | head -3
'
