#!/usr/bin/env bash
# READ-ONLY CRM crash-safety audit (Part A). Changes nothing.
echo "===== A1: Caddy routing isolation ====="
echo "-- caddy validate (live config) --"
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tail -2
echo "-- Twenty paths via public domain (expect they reach the CRM, NOT a 401 gate) --"
for p in "/" "/healthz" "/graphql" "/metadata" "/rest" "/auth/google" "/assets/x.js" "/fonts/x.woff2" "/images/x.png" "/financexyz"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://crm.nobridge.co$p")
  echo "  $p -> $code"
done
echo "-- /finance gate --"
echo -n "  /finance (no auth, expect 401): "; curl -s -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
echo -n "  /finance (auth,   expect 200): "; curl -s -u "nobridge:${FINANCE_BASIC_AUTH_PW:-retired}" -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
echo "-- asset cache headers preserved? --"
curl -s -D - -o /dev/null "https://crm.nobridge.co/fonts/x.woff2" | grep -i 'cache-control' | sed 's/^/  fonts: /' || echo "  (no cache-control)"
curl -s -D - -o /dev/null "https://crm.nobridge.co/assets/x.js"   | grep -i 'cache-control' | sed 's/^/  assets: /' || echo "  (no cache-control)"

echo; echo "===== A2: container / network / port isolation ====="
docker ps --format '{{.Names}} | {{.Ports}}'
echo "-- each container -> its network(s) --"
docker inspect -f '{{.Name}} -> {{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' $(docker ps -q)

echo; echo "===== A3: resource headroom (8 GB VM) ====="
free -h | head -2
docker stats --no-stream --format '{{.Name}} | mem {{.MemUsage}} ({{.MemPerc}}) | cpu {{.CPUPerc}}'
echo -n "disk: "; df -h / | tail -1
echo -n "backups: "; du -sh ~/finance/backups 2>/dev/null; echo -n "backup count: "; ls -1 ~/finance/backups 2>/dev/null | wc -l
echo "-- OOM kills (expect none) --"
sudo dmesg 2>/dev/null | grep -i -E 'out of memory|killed process|oom-kill' | tail -5 || echo "  (none found)"

echo; echo "===== A4: overlay + rollback points ====="
echo -n "front-build backups: "; ls -d ~/twenty/front-build.bak.* 2>/dev/null | tr '\n' ' '; echo
echo -n "stock compose backup present: "; ls ~/twenty/docker-compose.yml.pre-overlay.bak >/dev/null 2>&1 && echo yes || echo no
echo -n "caddy backups: "; sudo ls /etc/caddy/Caddyfile.bak.* 2>/dev/null | tr '\n' ' '; echo

echo; echo "===== A5: systemd timers ====="
systemctl list-timers --all --no-pager 2>/dev/null | grep -iE 'finance|client|sync|NEXT' | head -10
echo "-- backup service last run --"
sudo journalctl -u finance-db-backup.service -n 3 --no-pager 2>/dev/null | tail -3 || echo "  (none)"

echo; echo "===== A6: CRM health ====="
echo -n "healthz: "; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/healthz
docker ps --format '{{.Names}} {{.Status}}' | grep twenty
echo "-- recent twenty-server errors (last 2h) --"
docker logs twenty-server-1 --since 2h 2>&1 | grep -iE 'error|fatal|unhandled' | tail -6 || echo "  (none)"
echo "===== END ====="
