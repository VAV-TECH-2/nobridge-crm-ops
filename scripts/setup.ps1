# Bootstrap the Nobridge CRM workspace on a new Windows machine (PowerShell).
# Idempotent - safe to re-run. Clones the two nested repos this root repo ignores.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
Write-Host "Workspace root: $Root"

# --- 1. Windows git config ---------------------------------------------------
Write-Host "Enabling long paths (twenty/ has 238-char paths)..."
git config --global core.longpaths true

# --- 2. Clone the nested repos if missing ------------------------------------
if (-not (Test-Path "$Root\twenty\.git")) {
    Write-Host "Cloning frontend fork VAV-TECH-2/CRM -> twenty\ (~600 MB, takes a while)..."
    git clone --origin vt2 https://github.com/VAV-TECH-2/CRM.git "$Root\twenty"
    git -C "$Root\twenty" remote add upstream https://github.com/twentyhq/twenty.git
    git -C "$Root\twenty" checkout ui/icon-box-sizing
    Write-Host "NOTE: you may see a checkout warning about"
    Write-Host "  packages/twenty-website/public/illustrations/pricing/Price vs price"
    Write-Host "  - that is an upstream case-collision artifact. It is HARMLESS. Do not 'fix' it."
} else {
    Write-Host "twenty\ already present - skipping clone."
}

if (-not (Test-Path "$Root\.crm-automations\dashboard\.git")) {
    Write-Host "Cloning ops dashboard VAV-TECH-2/nobridge-ops-dashboard -> .crm-automations\dashboard\..."
    git clone https://github.com/VAV-TECH-2/nobridge-ops-dashboard.git "$Root\.crm-automations\dashboard"
} else {
    Write-Host ".crm-automations\dashboard\ already present - skipping clone."
}

# --- 3. Sanity checks ---------------------------------------------------------
Write-Host ""
Write-Host "Repo status:"
Write-Host ("  root (nobridge-crm-ops): " + (git -C $Root rev-parse --abbrev-ref HEAD))
Write-Host ("  twenty\:                 " + (git -C "$Root\twenty" rev-parse --abbrev-ref HEAD))
Write-Host ("  dashboard\:              " + (git -C "$Root\.crm-automations\dashboard" rev-parse --abbrev-ref HEAD))

if (-not (Test-Path "$Root\.crm-sales-engine\engine_twenty_token.txt")) {
    Write-Host ""
    Write-Host "WARNING: Secrets not restored yet. Get the secrets bundle zip from the team lead,"
    Write-Host "  then run:  powershell -File scripts\restore-secrets.ps1 C:\path\to\nobridge-crm-secrets-<date>.zip"
}

Write-Host ""
Write-Host "Done. Next: read ONBOARDING.md (top to bottom) before touching anything."
Write-Host "IMPORTANT: run the .sh ops scripts from Git Bash, not PowerShell."
