#!/usr/bin/env bash
# Installs the /finance-enabled Caddyfile safely:
#   backup -> validate NEW config -> (only if valid) install + reload -> verify.
# If validation fails, the live Caddyfile is left untouched.
set -u
NEW=/tmp/Caddyfile.finance
sed -i 's/\r$//' "$NEW"

TS=$(date +%Y%m%d-%H%M%S)
sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$TS"
echo "backed up live Caddyfile -> /etc/caddy/Caddyfile.bak.$TS"

echo '--- validating new config ---'
if ! caddy validate --adapter caddyfile --config "$NEW"; then
  echo 'VALIDATION_FAILED — live config untouched, nothing reloaded'
  exit 1
fi
echo 'VALID — installing + reloading caddy'
sudo cp "$NEW" /etc/caddy/Caddyfile
sudo systemctl reload caddy
sleep 2

echo '--- verify (HTTP codes) ---'
printf 'CRM root         : '; curl -s -o /dev/null -w '%{http_code}\n' https://crm.nobridge.co/
printf '/finance no-auth : '; curl -s -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
printf '/finance w/ auth : '; curl -s -u "nobridge:${FINANCE_BASIC_AUTH_PW:-retired}" -o /dev/null -w '%{http_code}\n' https://fin.nobridge.co
printf '/finance dash API: '; curl -s -u "nobridge:${FINANCE_BASIC_AUTH_PW:-retired}" -o /dev/null -w '%{http_code}\n' 'https://fin.nobridge.co/api/dashboard?period=overall'
printf 'caddy active     : '; systemctl is-active caddy
