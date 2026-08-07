# CLAUDE.md — Nobridge CRM ops workspace

**Read [`README.md`](./README.md) in this folder before doing anything.** It documents the live architecture, every service, where each credential lives, and the setup steps for a new machine. (Claude auto-loads this CLAUDE.md but not the README — so go read it.)

This is an **operations workspace**, not one app. It holds the CRM frontend source (`twenty/`), deploy/infra config (`deploy/`), and Python scripts (`.crm-*/`) that talk to the **live production server** at `crm.nobridge.co`.

## Non-negotiable safety rules
1. **Pin Twenty to `v2.7.3`. Never boot `latest`** — it migrates the DB forward and the pinned image then crashes (Postgres `42703`). Backend runs the stock image; only the frontend is customized.
2. **Many scripts here mutate production.** Before running one, find it in the README's Directory Guide and confirm it's LIVE vs HISTORICAL vs a `_`-prefixed scratch file. Prefer the idempotent setup scripts; treat `import_*`/`migrate_*`/`vm-rollback.sh` as dangerous.
3. **Secrets live here:** `.crm-sales-engine/engine_twenty_token.txt` (live API JWT) and `_archive/*.{zip,tgz}` (plaintext old creds). Treat the whole folder as sensitive; never paste secrets into chat, commits, or shared locations.

The VM key (`~/.ssh/id_rsa`), the Sales Engine (`Desktop\Sales Engine VM`), and the Finance app source (`Desktop\Nobridge Finance\nobridge-finance`) are **outside this folder** — see README §7.

> **Retired 2026-08-07 — do not resurrect without being asked.** The buy-side / sell-side / fulfillment rules engines and the Claude MCP connector are gone (README §10). The `nobridge-sales-engine` container now runs **only** Call Intelligence. Their code is still in `Desktop\Sales Engine VM` but is dormant and its state tables were wiped — `PIPELINE_ENGINES_ENABLED` is a tombstone, not a switch. The rules live on in [`WORKFLOWS.md`](./WORKFLOWS.md).

## Team & cross-OS context (Mac + Windows teammates)
This folder is **three git repos in one tree** — never `git add` across their boundaries:
- Root = `VAV-TECH-2/nobridge-crm-ops` (**public**), remote `origin`.
- `twenty/` = `VAV-TECH-2/CRM` (public), canonical remote **`vt2`**, prod branch `ui/icon-box-sizing`. Ignored by the root repo. (As of 2026-07-27 `origin` also points at `VAV-TECH-2/CRM` — the old `VAV-Technologies` org is retired.)
- `.crm-automations/dashboard/` = `VAV-TECH-2/nobridge-ops-dashboard` (private), remote `origin`. Ignored by the root repo.

Rules for every agent on every OS:
4. **The root repo is PUBLIC. Never commit secrets, PII, or weaken `.gitignore`.** The gitignored files in `.crm-sales-engine/` (token + 5 credential-bearing scripts) are *supposed* to be invisible to git — on a fresh clone they come from the secrets bundle (`scripts/restore-secrets.{sh,ps1}`), not from git. If `git status` ever shows `engine_twenty_token.txt`, stop and fix `.gitignore`.
5. **Sync before work, push after:** `git pull` (root), `git -C twenty pull vt2 ui/icon-box-sizing`, `git -C .crm-automations/dashboard pull`. Trunk-based, pull-before-push.
6. **Line endings:** `.gitattributes` pins LF everywhere (CRLF only for `*.ps1`). Never set `core.autocrlf` or "normalize" line endings in bulk.
7. **On Windows:** run `.sh` scripts from **Git Bash** (never PowerShell/cmd); `core.longpaths` must be true; never pipe scripts into SSH from PowerShell (UTF-8 BOM corrupts them — `scp` a file instead); the `Price/`↔`price/` case-collision warning when checking out `twenty/` is a harmless upstream artifact — never "fix" it.
8. **Paths:** Mac = `~/Desktop/Nobridge Software/CRM`, Windows = `%USERPROFILE%\Desktop\Nobridge Software\CRM`. Quote paths — the folder name contains a space. Old notes saying `Desktop\CRM` mean this folder.

New machine? Follow [`ONBOARDING.md`](./ONBOARDING.md).
