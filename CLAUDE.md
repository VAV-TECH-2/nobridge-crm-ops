# CLAUDE.md — Nobridge CRM ops workspace

**Read [`README.md`](./README.md) in this folder before doing anything.** It documents the live architecture, every service, where each credential lives, and the setup steps for a new machine. (Claude auto-loads this CLAUDE.md but not the README — so go read it.)

This is an **operations workspace**, not one app. It holds the CRM frontend source (`twenty/`), deploy/infra config (`deploy/`), and Python scripts (`.crm-*/`) that talk to the **live production server** at `crm.nobridge.co`.

## Non-negotiable safety rules
1. **Pin Twenty to `v2.7.3`. Never boot `latest`** — it migrates the DB forward and the pinned image then crashes (Postgres `42703`). Backend runs the stock image; only the frontend is customized.
2. **Many scripts here mutate production.** Before running one, find it in the README's Directory Guide and confirm it's LIVE vs HISTORICAL vs a `_`-prefixed scratch file. Prefer the idempotent setup scripts; treat `import_*`/`migrate_*`/`vm-rollback.sh` as dangerous.
3. **Secrets live here:** `.crm-sales-engine/engine_twenty_token.txt` (live API JWT) and `_archive/*.{zip,tgz}` (plaintext old creds). Treat the whole folder as sensitive; never paste secrets into chat, commits, or shared locations.

The VM key (`~/.ssh/id_rsa`), the Sales Engine (`Desktop\Sales Engine VM`), and the Finance app source (`Desktop\Nobridge Finance\nobridge-finance`) are **outside this folder** — see README §7.

> **Retired 2026-08-07 — do not resurrect without being asked.** The buy-side / sell-side / fulfillment rules **engines** and the Claude MCP connector are gone (README §10). The `nobridge-sales-engine` container now runs **only** Call Intelligence. Their code is still in `Desktop\Sales Engine VM` but is dormant and its state tables were wiped — `PIPELINE_ENGINES_ENABLED` is a tombstone, not a switch.
>
> The **rules** are not retired — they are how the pipeline is worked by hand. Since 2026-08-09 there is exactly **one source** for them: [`.crm-automations/dashboard/workflow_spec.py`](./.crm-automations/dashboard/workflow_spec.py). [`WORKFLOWS.md`](./WORKFLOWS.md), the **High Level Workflows** tab (stages, steps, loops as config panels) and the **Workflow** tab (the same thing with every loop unrolled per touch) are all **generated** from it. Edit the spec and regenerate — `python3 workflow_doc.py > ../../WORKFLOWS.md` — never edit the outputs. The old arrangement was four hand-kept copies with nothing checking they agreed, and they did not: five chase ladders stopped dead, which is where 24 hanging states came from.

## ✅ The CRM is on v2 (applied 2026-08-09)
The documented workflow is **v2**: 9/10/9 stages, 135 steps, 12 named loops (L1–L12), each loop carrying its touches, schedule, entry, exit and — the row that did not exist before — what happens when it runs out. **`WORKFLOWS.md` now describes the live CRM.** `_archive/WORKFLOWS-pre-v2.md` is history; do not work deals from it.

What went in: 45 new fields across the four boards, the v2 stage sets (buy/other 9, sell 10, fulfillment 9), Final Decision at 8 verdicts including `Do Not Contact`, **449 records re-staged**, the old stage options removed, and option labels/order matched to the spec. 487 records, none lost, `05_verify.py` passing. Full account, including the three bugs that only surfaced on apply: [`.crm-migrate-v2/RUNBOOK.md`](./.crm-migrate-v2/RUNBOOK.md). Team-facing version: [`MIGRATION.md`](./MIGRATION.md) — **not yet updated, still describes the change as pending.**

**`clienttype-sync` was broken by this and has been fixed** (same day). Its `SEG` map hardcoded the stage each new record is created at, and `NEW_LEAD` / `REACHED_OUT` no longer exist, so tagging a company silently produced nothing. Now `LEAD` / `TARGET` / `LEAD` / `APPROACH`, with `NETWORK` left on `REACHED_OUT` because `networking` was out of scope for v2 and still has it. Canonical copy is [`.crm-automations/clienttype-sync/sync.py`](./.crm-automations/clienttype-sync/sync.py) (identical to the VM's `/opt/heydeal-clienttype-sync/sync.py`; deploy = `scp` + it is a oneshot on a 2-min timer). VM backup: `sync.py.bak-pre-v2-20260809`. Verified by actually creating one record per board and deleting it — a clean sync run proves nothing here, because it reports `create=0` until somebody tags a company.

**`stage` has no default** on any board (was `'NEW_LEAD'` on three; cleared because `06` cannot remove an option the field defaults to). A record created without an explicit stage lands with no stage and will not appear on the kanban. Tagging a company is unaffected — the sync sets the stage explicitly.

**On retiring Sell's `engagementStatus` (RUNBOOK §7):** `Do Not Contact` now exists as a verdict, and — checked 2026-08-09, including soft-deleted rows — **zero records carry `CRASH_OUT_DNC`**, so there is no data to migrate and nothing to lose. That is a *snapshot*, not a permanent clearance: re-run the check before retiring the field, because it is still the only place a do-not-contact request can be recorded until someone starts using the verdict.

Phase 2 (RUNBOOK §7) is untouched: no script here has ever modified an existing field, so `progressType`, the `mandate` relation, the `actionItem` relabel and the four retirements are all still to do.

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
