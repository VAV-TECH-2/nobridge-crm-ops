# Restore the secrets bundle into this workspace (Windows PowerShell).
# Usage: powershell -File scripts\restore-secrets.ps1 C:\path\to\nobridge-crm-secrets-<date>.zip
#
# Note: the bundle is a password-protected zip. PowerShell's Expand-Archive
# cannot read encrypted zips, so this script uses 7-Zip if installed, and
# otherwise tells you to extract via File Explorer (which handles the password).
param([Parameter(Mandatory = $true)][string]$ZipPath)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $ZipPath)) { throw "No such file: $ZipPath" }

$SevenZip = Get-Command 7z -ErrorAction SilentlyContinue
if (-not $SevenZip -and (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) {
    $SevenZip = "$env:ProgramFiles\7-Zip\7z.exe"
}

if ($SevenZip) {
    Write-Host "Extracting with 7-Zip into $Root (password prompt follows)..."
    & $SevenZip x $ZipPath "-o$Root" -y -xr'!RESTORE.txt'
    if ($LASTEXITCODE -ne 0) { throw "7-Zip extraction failed." }
} else {
    Write-Host "7-Zip not found. Do this instead:"
    Write-Host "  1. Right-click the zip in File Explorer -> Extract All"
    Write-Host "  2. Set the destination to:  $Root   (enter the password when asked, merge folders)"
    Write-Host "  3. Re-run this script afterwards to verify."
    if (-not (Test-Path "$Root\.crm-sales-engine\engine_twenty_token.txt")) { exit 1 }
}

Write-Host ""
Write-Host "Verifying..."
$ok = $true
@(
    ".crm-sales-engine\engine_twenty_token.txt",
    ".crm-sales-engine\digest_and_demo.py",
    ".crm-sales-engine\naluri.py",
    ".crm-sales-engine\test_e2e.py",
    ".crm-sales-engine\test_reconcile.py",
    ".crm-sales-engine\oauth_exchange.py"
) | ForEach-Object {
    if (Test-Path "$Root\$_") { Write-Host "  OK      $_" }
    else { Write-Host "  MISSING $_"; $script:ok = $false }
}

# Paranoia: these must be invisible to git. If git sees them, .gitignore broke.
$gitSees = git -C $Root status --porcelain | Select-String "engine_twenty_token"
if ($gitSees) { Write-Host "  WARNING: git sees the token file - .gitignore broken, DO NOT COMMIT."; $ok = $false }

if ($ok) { Write-Host "Done. Now DELETE the zip: Remove-Item '$ZipPath'" } else { exit 1 }
