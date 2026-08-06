#!/usr/bin/env bash
# Build the password-protected secrets bundle to hand to a teammate.
# The public repo excludes these files (see .gitignore); this zip is the ONLY
# way they should travel. Share the ZIP and the PASSWORD over two different
# channels (e.g. zip via Drive, password via WhatsApp/voice).
#
# Usage: bash scripts/make-secrets-bundle.sh
# Output: ~/Desktop/nobridge-crm-secrets-<date>.zip  (never inside the repo)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HOME/Desktop/nobridge-crm-secrets-$(date +%Y%m%d).zip"

# Every path here is gitignored in the public repo. Keep this list in sync
# with the "SECRETS" section of .gitignore.
FILES=(
  ".crm-sales-engine/engine_twenty_token.txt"
  ".crm-sales-engine/test_e2e.py"
  ".crm-sales-engine/test_reconcile.py"
  ".crm-sales-engine/oauth_exchange.py"
)

cd "$ROOT"
MISSING=0
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "MISSING: $f"; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || { echo "Aborting — some secret files are missing on this machine."; exit 1; }

# RESTORE.txt travels inside the zip so the recipient knows what to do.
RESTORE="$(mktemp -d)/RESTORE.txt"
cat > "$RESTORE" <<'EOF'
NOBRIDGE CRM — SECRETS BUNDLE
=============================
These files are deliberately excluded from the public GitHub repo
(VAV-TECH-2/nobridge-crm-ops). Restore them into your local clone.

The zip already contains the correct relative paths, so restoring is just
"extract into the workspace root":

  Mac / Linux / Git Bash:
    unzip nobridge-crm-secrets-<date>.zip -d ~/Desktop/"Nobridge Software"/CRM
    (or: bash scripts/restore-secrets.sh /path/to/this.zip)

  Windows:
    Right-click the zip -> Extract All (enter the password) -> extract INTO
    %USERPROFILE%\Desktop\Nobridge Software\CRM  (merge folders)
    (or: powershell -File scripts\restore-secrets.ps1 C:\path\to\this.zip)

Files and what they are:
  .crm-sales-engine/engine_twenty_token.txt  live Twenty API JWT (prod!)
  .crm-sales-engine/test_e2e.py              OAuth client secret + refresh token
  .crm-sales-engine/test_reconcile.py        OAuth client secret + refresh token
  .crm-sales-engine/oauth_exchange.py        OAuth client secret

RULES
  - NEVER commit these files or this zip to any repo (they are gitignored —
    do not "fix" that).
  - NEVER paste their contents into chats, issues, or AI prompts.
  - Delete this zip after extracting it.
EOF

rm -f "$OUT"
echo "Creating $OUT — choose a strong password when prompted…"
zip -e -j "$OUT" "$RESTORE"                    # RESTORE.txt at zip root
zip -e "$OUT" "${FILES[@]}"                    # secret files with relative paths

echo
echo "✅ Bundle written to: $OUT"
echo "   Share the ZIP and the PASSWORD via two different channels."
echo "   Tell the teammate to delete the zip after restoring."
