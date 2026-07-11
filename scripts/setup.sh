#!/usr/bin/env bash
# Bootstrap the Nobridge CRM workspace on a new machine (Mac / Linux / Git Bash on Windows).
# Idempotent — safe to re-run. Clones the two nested repos this root repo deliberately ignores.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "Workspace root: $ROOT"

# --- 1. Windows-specific git config (no-ops elsewhere) ----------------------
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    echo "Windows detected: enabling long paths (twenty/ has 238-char paths)…"
    git config --global core.longpaths true
    ;;
esac

# --- 2. Clone the nested repos if missing -----------------------------------
if [ ! -d "$ROOT/twenty/.git" ]; then
  echo "Cloning frontend fork VAV-TECH-2/CRM -> twenty/ (~600 MB, takes a while)…"
  git clone --origin vt2 https://github.com/VAV-TECH-2/CRM.git "$ROOT/twenty"
  git -C "$ROOT/twenty" remote add upstream https://github.com/twentyhq/twenty.git
  git -C "$ROOT/twenty" checkout ui/icon-box-sizing
  echo "NOTE: on Windows you may see a checkout warning about"
  echo "  packages/twenty-website/public/illustrations/pricing/Price vs price"
  echo "  — that is an upstream case-collision artifact. It is HARMLESS. Do not 'fix' it."
else
  echo "twenty/ already present — skipping clone."
fi

if [ ! -d "$ROOT/.crm-automations/dashboard/.git" ]; then
  echo "Cloning ops dashboard VAV-TECH-2/nobridge-ops-dashboard -> .crm-automations/dashboard/…"
  git clone https://github.com/VAV-TECH-2/nobridge-ops-dashboard.git "$ROOT/.crm-automations/dashboard"
else
  echo ".crm-automations/dashboard/ already present — skipping clone."
fi

# --- 3. Sanity checks --------------------------------------------------------
echo
echo "Repo status:"
printf '  %-28s %s\n' "root (nobridge-crm-ops):" "$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'NOT A REPO?')"
printf '  %-28s %s\n' "twenty/:"                 "$(git -C "$ROOT/twenty" rev-parse --abbrev-ref HEAD 2>/dev/null || echo MISSING)"
printf '  %-28s %s\n' "dashboard/:"              "$(git -C "$ROOT/.crm-automations/dashboard" rev-parse --abbrev-ref HEAD 2>/dev/null || echo MISSING)"

if [ ! -f "$ROOT/.crm-sales-engine/engine_twenty_token.txt" ]; then
  echo
  echo "⚠️  Secrets not restored yet. Get the secrets bundle zip from the team lead,"
  echo "   then run:  bash scripts/restore-secrets.sh /path/to/nobridge-crm-secrets-<date>.zip"
fi

echo
echo "Done. Next: read ONBOARDING.md (top to bottom) before touching anything."
