#!/usr/bin/env bash
# Restore the secrets bundle into this workspace (Mac / Linux / Git Bash).
# Usage: bash scripts/restore-secrets.sh /path/to/nobridge-crm-secrets-<date>.zip
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIP="${1:?Usage: bash scripts/restore-secrets.sh /path/to/nobridge-crm-secrets-<date>.zip}"
[ -f "$ZIP" ] || { echo "No such file: $ZIP"; exit 1; }

echo "Extracting into $ROOT (you will be prompted for the bundle password)…"
unzip -o "$ZIP" -d "$ROOT" -x RESTORE.txt

echo
echo "Verifying…"
OK=1
for f in \
  ".crm-sales-engine/engine_twenty_token.txt" \
  ".crm-sales-engine/digest_and_demo.py" \
  ".crm-sales-engine/naluri.py" \
  ".crm-sales-engine/test_e2e.py" \
  ".crm-sales-engine/test_reconcile.py" \
  ".crm-sales-engine/oauth_exchange.py"; do
  if [ -f "$ROOT/$f" ]; then echo "  ✅ $f"; else echo "  ❌ MISSING $f"; OK=0; fi
done

# All of these are gitignored — confirm git agrees (paranoia check).
if git -C "$ROOT" status --porcelain | grep -q ".crm-sales-engine/engine_twenty_token.txt"; then
  echo "  ⚠️  git sees the token as an untracked change — .gitignore is broken, DO NOT COMMIT."
  OK=0
fi

[ "$OK" -eq 1 ] && echo "Done. Now DELETE the zip: rm '$ZIP'" || exit 1
