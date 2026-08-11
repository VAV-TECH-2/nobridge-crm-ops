# CLAUDE.md — Nobridge CRM ops workspace

**Read [`README.md`](./README.md) in this folder before doing anything.** It documents the live architecture, every service, where each credential lives, and the setup steps for a new machine. (Claude auto-loads this CLAUDE.md but not the README — so go read it.)

This is an **operations workspace**, not one app. It holds the CRM frontend source (`twenty/`), deploy/infra config (`deploy/`), and Python scripts (`.crm-*/`) that talk to the **live production server** at `crm.nobridge.co`.

## Non-negotiable safety rules
1. **Pin Twenty to `v2.7.3`. Never boot `latest`** — it migrates the DB forward and the pinned image then crashes (Postgres `42703`). Backend runs the stock image; only the frontend is customized.
2. **Many scripts here mutate production.** Before running one, find it in the README's Directory Guide and confirm it's LIVE vs HISTORICAL vs a `_`-prefixed scratch file. Prefer the idempotent setup scripts; treat `import_*`/`migrate_*`/`vm-rollback.sh` as dangerous.
3. **Secrets live here:** `.crm-sales-engine/engine_twenty_token.txt` (live API JWT) and `_archive/*.{zip,tgz}` (plaintext old creds). Treat the whole folder as sensitive; never paste secrets into chat, commits, or shared locations.

The VM key (`~/.ssh/id_rsa`), the Sales Engine (`Desktop\Sales Engine VM`), and the Finance app source (`Desktop\Nobridge Finance\nobridge-finance`) are **outside this folder** — see README §7.

> **Retired 2026-08-07 — do not resurrect without being asked.** The buy-side / sell-side / fulfillment rules **engines** are gone (README §10), and so was the Claude MCP connector — **that one was asked for and rebuilt on 2026-08-11 as `ai-access`, see below; the engines were not.** The `nobridge-sales-engine` container now runs **only** Call Intelligence. Their code is still in `Desktop\Sales Engine VM` but is dormant and its state tables were wiped — `PIPELINE_ENGINES_ENABLED` is a tombstone, not a switch.
>
> The **rules** are not retired — they are how the pipeline is worked by hand. Since 2026-08-09 there is exactly **one source** for them: [`.crm-automations/dashboard/workflow_spec.py`](./.crm-automations/dashboard/workflow_spec.py). [`WORKFLOWS.md`](./WORKFLOWS.md), the **High Level Workflows** tab (stages, steps, loops as config panels) and the **Workflow** tab (the same thing with every loop unrolled per touch) are all **generated** from it. Edit the spec and regenerate — `python3 workflow_doc.py > ../../WORKFLOWS.md` — never edit the outputs. The old arrangement was four hand-kept copies with nothing checking they agreed, and they did not: five chase ladders stopped dead, which is where 24 hanging states came from.

## ✅ The CRM is on v2 (applied 2026-08-09)
The documented workflow is **v2**: 9/10/9 stages, 135 steps, 12 named loops (L1–L12), each loop carrying its touches, schedule, entry, exit and — the row that did not exist before — what happens when it runs out. **`WORKFLOWS.md` now describes the live CRM.** `_archive/WORKFLOWS-pre-v2.md` is history; do not work deals from it.

What went in: 45 new fields across the four boards, the v2 stage sets (buy/other 9, sell 10, fulfillment 9), Final Decision at 8 verdicts including `Do Not Contact`, **449 records re-staged**, the old stage options removed, and option labels/order matched to the spec. 487 records, none lost, `05_verify.py` passing. Full account, including the three bugs that only surfaced on apply: [`.crm-migrate-v2/RUNBOOK.md`](./.crm-migrate-v2/RUNBOOK.md). Team-facing version: [`MIGRATION.md`](./MIGRATION.md) — **not yet updated, still describes the change as pending.**

**`clienttype-sync` was broken by this and has been fixed** (same day). Its `SEG` map hardcoded the stage each new record is created at, and `NEW_LEAD` / `REACHED_OUT` no longer exist, so tagging a company silently produced nothing. Now `LEAD` / `TARGET` / `LEAD` / `APPROACH`, with `NETWORK` left on `REACHED_OUT` because `networking` was out of scope for v2 and still has it. Canonical copy is [`.crm-automations/clienttype-sync/sync.py`](./.crm-automations/clienttype-sync/sync.py) (identical to the VM's `/opt/heydeal-clienttype-sync/sync.py`; deploy = `scp` + it is a oneshot on a 2-min timer). VM backup: `sync.py.bak-pre-v2-20260809`. Verified by actually creating one record per board and deleting it — a clean sync run proves nothing here, because it reports `create=0` until somebody tags a company.

**`stage` has no default** on any board (was `'NEW_LEAD'` on three; cleared because `06` cannot remove an option the field defaults to). A record created without an explicit stage lands with no stage and will not appear on the kanban. Tagging a company is unaffected — the sync sets the stage explicitly.

**On retiring Sell's `engagementStatus` (RUNBOOK §7):** `Do Not Contact` now exists as a verdict, and — checked 2026-08-09, including soft-deleted rows — **zero records carry `CRASH_OUT_DNC`**, so there is no data to migrate and nothing to lose. That is a *snapshot*, not a permanent clearance: re-run the check before retiring the field, because it is still the only place a do-not-contact request can be recorded until someone starts using the verdict.

Phase 2 (RUNBOOK §7) is untouched: no script here has ever modified an existing field, so `progressType`, the `mandate` relation, the `actionItem` relabel and the four retirements are all still to do.

## 🤖 The CRM now updates itself — `pipeline-autopilot` (live 2026-08-11)
An hourly systemd timer reads the synced email, calendar and Call Intelligence output and **writes to
production**: stage, contact dates, next owner, next action due, meeting outcome, qualified, owner,
"where we last left off", and a note when something happened. Source
[`.crm-automations/pipeline-autopilot/`](./.crm-automations/pipeline-autopilot/), deployed to
`/opt/nobridge-pipeline-autopilot/`, card + docs + an **Autopilot tab** on node.nobridge.co.

**It reads [`workflow_spec.py`](./.crm-automations/dashboard/workflow_spec.py) at runtime.** That is
the whole design: the rules it acts on are the same ones `WORKFLOWS.md` and the Workflow tab are
generated from, so behaviour and documentation cannot drift. Edit the spec, deploy it, behaviour
changes — no code edit. The spec gained a machine-readable layer for this (`sets`, `anchor`, `when`,
`stops_on`, `at_mode`, `sla_days`), all invisible to the generated doc; `WORKFLOWS.md` regenerates
byte-identical apart from the intended `who` changes.

Rules for anyone touching it:
- **`preflight.py` runs before every pass and refuses the run on any blocker.** It is what would have
  caught the clienttype-sync breakage on migration day. If you rename a stage or field in the spec,
  deploy the spec too — a stale deployed copy is a blocker, not a warning.
- **`revert.py --run N --apply` undoes a run**, using the old value recorded for every write. It
  skips anything a human has changed since. This is why autonomous writing is acceptable; don't
  remove the audit trail. `data/autopilot.db` is **gitignored but not disposable** — it holds email
  bodies (PII, and this repo is public) *and* is the only way to undo anything.
- **Guardrails, all deliberate:** one stage forward or straight to Closed; never out of Closed; never
  close without a verdict; one stage move per deal per day; a circuit breaker that aborts a run
  touching >25 records or >15% of a sample of 20+; confidence floors of 0.75 stage / 0.60 field /
  0.90 Do-Not-Contact-with-a-quote.
- **It never sends email**, so every "send the X" step in the spec is still a person's job — it only
  stamps that it happened. And it **cannot see cold outreach** (Instantly sending domains never sync),
  so L1/L11/L12 touches are timed from the anchor field, not observed.
- **Privacy:** it reads all three mailboxes' bodies and sends extracts to Azure OpenAI. That works
  only because all three `messageChannel` rows are `SHARE_EVERYTHING`. Setting one back to `METADATA`
  silently blinds it on that mailbox.

## 🧠 You can talk to the CRM now — `ai-access` (live 2026-08-11)
A connector at **`node.nobridge.co/ai/`** that lets Claude (MCP, token in the URL) or a ChatGPT
custom GPT (OpenAPI Actions, Bearer) read the pipeline and change it. Source
[`.crm-automations/ai-access/`](./.crm-automations/ai-access/), deployed to `/opt/nobridge-ai-access/`,
systemd unit `nobridge-ai-access`, plus an **AI Access tab** on node.nobridge.co.

**This deliberately replaces the ops MCP connector retired 2026-08-07** — the tombstone below said
"do not resurrect without being asked", and it was asked for. The old one failed because it exposed
raw CRM tools that understood nothing about the pipeline. The difference is
[`context.py`](./.crm-automations/ai-access/context.py): a **context engine** that hands the AI the
boards, every field and its meaning, the workflow stage by stage, the 12 ladders and a `gotchas`
section *before* it answers anything — all generated from the live metadata API and from
`workflow_spec.py`, so it cannot describe rules nobody follows. Old `/mcp/<token>` URLs still 404;
this lives on `/ai/` on purpose.

**It reuses rather than reimplements.** `deps.py` puts the autopilot's modules on `sys.path` and
imports them: one `twclient`, one `crm`, one `db`, one `rules`, one `store`, one `revert`, and through
`spec.py` one `workflow_spec.py`. Nothing about the pipeline is decided twice.

Rules for anyone touching it:
- **Writes go through `rules.validate(..., actor="human")`** — the autopilot's own validator, with one
  additive parameter. `actor="human"` skips *only* the confidence bars (nothing to infer when a person
  has said what they want). One stage forward or straight to Closed, never backwards, never out of
  Closed, never closed without a verdict, only fields a step at that stage authorises: all identical.
  Pacing (one stage move per deal per day) yields to a person but is flagged and recorded.
- **Every write tool needs `confirm: true`.** Without it, it returns the diff and changes nothing. The
  confirmation belongs in the conversation, not in the CRM afterwards.
- **AI writes land in `autopilot.db` with `source='ai'` and the asking person in `actor`**, so
  `revert.py --run N --apply` undoes them with no new tooling. Do not give this its own write log.
  `data/aiaccess.db` holds only tokens and the request log — gitignored, and not disposable.
- **`selfcheck.py` runs as `ExecStartPre`; a blocker means the unit does not start.** It caught the
  first deploy: the VM's autopilot copy predated a function this needs. If you change the spec or the
  autopilot, deploy them too.
- **Per-person tokens** (`tokens.py --issue <email> --scope read|write [--boards …]`), sha256 only, so
  a token is shown once and never again. Access also requires a live Admin/Manager role in the CRM —
  removing somebody there removes this. Unknown or revoked → **bare 404**, never 401.
- **`/.well-known/oauth-*` and `/register` must 404 on node.nobridge.co** or MCP clients try to sign
  in and fail confusingly — the `fin.nobridge.co` lesson of 2026-07-28. It is in the Caddyfile.
- **It never sends email either.** The unlock is that the same AI holds your mailbox: send there,
  stamp the CRM here. It cannot see cold outreach, same blind spot as the autopilot.

**One spec problem it surfaced and did not fix:** `sets` doubles as *what a step writes* and *the
allowlist for that stage*, so B74/S74 ("Out for signature") list `contractSignedAt: now` and
B32/B52/S32/S52 list `escalatedAt: now` — fields belonging to a *later* event. Applied literally,
stamping "out for signature" would mark the contract signed. `guard.py` reads the step's prose to tell
the two apart (`_valued_in_prose`) and reports the rest instead of writing it. The real fix is in the
spec — a way to say *authorised here, set elsewhere* — and that is a rules change, so it is written up,
not done unilaterally. The autopilot was never affected.

**A real bug fixed in `rules.py` while building this:** when a close was refused for having no verdict,
`writes["stage"]` had already been set by the clamp above and was never removed — so the refusal was
logged and the stage written anyway, minus its `stageChangedAt`. Exactly the hanging state the check
exists to prevent, with a log line claiming it had been prevented. One `writes.pop("stage", None)`.

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
