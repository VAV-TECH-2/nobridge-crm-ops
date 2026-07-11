#!/usr/bin/env bash
# Sets up a nightly pg_dump backup of finance-db (systemd timer), then runs one
# backup immediately to verify. Backups kept in ~/finance/backups (last 14).
set -u

# 1. Backup script (quoted heredoc -> no expansion now; runs at backup time)
cat > /home/azureuser/finance/backup-finance-db.sh <<'EOF'
#!/usr/bin/env bash
set -u
BACKUP_DIR=/home/azureuser/finance/backups
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
docker exec nobridge-finance-db pg_dump -U finance -d finance -Fc > "$BACKUP_DIR/finance-$TS.dump"
# keep the 14 most recent
ls -1t "$BACKUP_DIR"/finance-*.dump 2>/dev/null | tail -n +15 | xargs -r rm -f
EOF
chmod +x /home/azureuser/finance/backup-finance-db.sh

# 2. systemd service + timer
sudo tee /etc/systemd/system/finance-db-backup.service >/dev/null <<'EOF'
[Unit]
Description=Nobridge Finance DB nightly backup
[Service]
Type=oneshot
User=azureuser
ExecStart=/home/azureuser/finance/backup-finance-db.sh
EOF
sudo tee /etc/systemd/system/finance-db-backup.timer >/dev/null <<'EOF'
[Unit]
Description=Daily Nobridge Finance DB backup
[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now finance-db-backup.timer

# 3. Run one backup now and verify
/home/azureuser/finance/backup-finance-db.sh
echo "--- backups present ---"
ls -lh /home/azureuser/finance/backups/
echo "--- next scheduled run ---"
systemctl list-timers finance-db-backup.timer --no-pager
