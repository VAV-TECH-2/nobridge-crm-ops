# Nobridge CRM — Operations Workspace

> **Read this first.** This folder is not a single application you can `npm start`. It is the **operations workspace** for the Nobridge business system: the source for a self-hosted CRM's UI, the deploy/infra config, and a set of Python scripts that talk to the live production server. **Several scripts here mutate production data.** Before running anything, find it in the [Directory Guide](#4-directory-guide) and check whether it is LIVE, HISTORICAL, or STALE.
>
> This document exists so that a fresh Claude Code agent on any machine has full context. It was written on **2026-07-06**; GitHub-based team sync added **2026-07-11**.
>
> **This workspace is on GitHub** as [`VAV-TECH-2/nobridge-crm-ops`](https://github.com/VAV-TECH-2/nobridge-crm-ops) (public — secrets are excluded and travel via a password-protected bundle instead). New machine or new teammate? Follow **[`ONBOARDING.md`](./ONBOARDING.md)** — it covers Mac and Windows side by side.

---

## 1. What this folder is

Three live web properties make up the Nobridge system, all hosted on **one Azure VM**:

| Property | URL | What it is |
|---|---|---|
| **CRM** | `crm.nobridge.co` | Self-hosted [Twenty CRM](https://twenty.com) v2.7.3 (stock Docker image + a custom frontend bundle overlaid on top). The core system. |
| **Finance** | `fin.nobridge.co` | "Nobridge Finance" — a separate Next.js app (cost/income submission → approvals → payment tracking + analytics). Fully isolated from the CRM. |
| **Ops** | `node.nobridge.co` | The ops dashboard (Calls · High Level Workflows · Workflow · Automations · Autopilot · AI Access · Logs) — read-only, Google sign-in, CRM Admin/Manager only, like Finance. Also hosts **AI Access** at `/ai/` (its own service and its own token auth), the connector Claude and ChatGPT use to read and change the CRM. The old `/mcp/*` connector was retired 2026-08-07 and still returns 404. |

This folder contains, for those properties:
- **`twenty/`** — the CRM frontend source (a fork-branch of the Twenty monorepo; only the frontend is customized).
- **`deploy/`** — docker-compose files, Caddy configs, and deploy/rollback scripts for the VM.
- **`.crm-*/`** — Python tooling: data migrations, schema setup, the ops-dashboard source, and sales-automation *setup* scripts.
- **`_archive/`** — retired code + backups (contains old plaintext secrets — treat as sensitive).

> ⚠️ **The Finance app source and the running Sales Engine are NOT in this folder.** See [§6 What does NOT live here](#6-what-does-not-live-in-this-folder).

---

## 2. Live system map

```
                        Internet (HTTPS)
                              │
                    ┌─────────▼──────────┐
                    │   Caddy (TLS +     │   /etc/caddy/Caddyfile
                    │   reverse proxy)   │   (source: deploy/Caddyfile.nobridge-final)
                    └─────────┬──────────┘
        ┌─────────────────────┼────────────────────────┐
        │                     │                        │
 crm.nobridge.co       fin.nobridge.co          node.nobridge.co
        │                     │                        │
        ▼                     ▼                        ▼
   127.0.0.1:3000       127.0.0.1:3100          127.0.0.1:3200  ← dashboard
   Twenty server        Nobridge Finance         127.0.0.1:3300  ← /ai/* AI Access
        │               (Next.js)                (dashboard.py · server.py)
        │                                        (127.0.0.1:8080 = the sales-engine
        │                                         container: call intelligence only,
        │                                         loopback, no longer proxied)
        │                     │
   ┌────┴─────┬──────────┐    └── finance-db (Postgres 17, own compose project
   │          │          │        "nobridge-finance", isolated network)
 worker    Postgres    Redis
           (v16)
   (compose project "twenty", dir /home/azureuser/twenty)

  Azure VM: vm-twenty-crm  ·  20.189.126.94  ·  size B2als_v2
  Login:    ssh azureuser@20.189.126.94   (key auth, passwordless sudo)
```

**Containers** (via `sudo docker ps` on the VM): `twenty-server-1`, `twenty-worker-1`, `twenty-db-1` (Postgres 16), a Redis container, plus the isolated `nobridge-finance` project (app + `finance-db` Postgres 17).

**Everything we run outside the stock CRM** — 13 jobs and services, all of them documented in plain language with flow diagrams at **node.nobridge.co → Automations → (any card) → How it works**. That tab is the source of truth for *how* each one works; the table below is just the inventory and where each is triggered from.

> ⚠️ **The three pipeline engines were retired 2026-08-07** — see §10. The container `nobridge-sales-engine` still exists but now runs **only** Call Intelligence. The Claude MCP connector went with them and **was rebuilt on 2026-08-11 as AI Access** (`/ai/`, below); the engines were not.

| What | Trigger | Cadence | Purpose |
|---|---|---|---|
| Call intelligence | container `nobridge-sales-engine` | every 15 min | Reads Gemini call notes from Meet, files a note + action items on the right records. **The only thing left in that container.** |
| Client Type sync | timer `clienttype-sync` | every 2 min | Mirrors `Company.clientType` → the 5 split opportunity boards. |
| `blocklist-guard` | timer | every 2 min | Enforces the cold-email sending-domain blocklist: mirrors the admin's blocklist (Settings → Accounts → Blocklist, vilca@nobridge.co = master list) to every member and soft-deletes Companies/People auto-created from blocked `@domain`s (skips records attached to real deals/notes; ids logged to `swept.json`). Source: `.crm-automations/blocklist-guard/`. |
| Gmail draft cleanup | timer `crm-draft-cleanup` | hourly | Soft-deletes the phantom "sent" messages Twenty's sync creates on every draft autosave. |
| Finance DB backup | timer `finance-db-backup` | nightly 03:30 | Dump of the Finance database. |
| **CRM DB backup** | **crontab** 03:15 | nightly | ⚠️ The only backup of the CRM database. `/usr/local/bin/twenty-backup.sh`. Failed silently for 73 nights (wrong `pg_dump` role, no size check) until 2026-08-06 — it now refuses to keep an undersized dump and the dashboard judges it on output freshness. |
| **Pipeline Autopilot** | timer `pipeline-autopilot` | hourly | Reads the synced email, calendar and call notes and updates the deals itself: stage, contact dates, next owner, next action due, meeting outcome, qualified, owner, "where we last left off", and a note when something happened. Rules come from `workflow_spec.py` at runtime, so it cannot drift from `WORKFLOWS.md`. Writes are capped (one stage move per deal per day, a circuit breaker on bulk moves) and every change is reversible with `revert.py`. |
| **AI Access** | service `nobridge-ai-access` | always on | `node.nobridge.co/ai/` — lets Claude (MCP, token in the URL) or a ChatGPT custom GPT read the pipeline and change it. Hands the AI the whole workflow before it answers (`context.py`, generated from `workflow_spec.py` + the live metadata API), validates every write through the autopilot's own `rules.validate`, needs `confirm: true` on anything that writes, and records changes in `autopilot.db` so `revert.py` undoes them. Per-person tokens, sha256 only. Source: `.crm-automations/ai-access/`. |
| ~~Last-contacted refresh~~ | ~~crontab 06:30/06:35~~ | — | **Retired.** Superseded by the autopilot, which writes the same fields hourly with the identical formula. Both cron lines are gone (`crontab -l` now holds only the 03:15 CRM backup, verified 2026-08-11); the SQL is still on the VM at `~/refresh-last-contacted.sql`. |
| Ops dashboard | service `heydeal-automations-dashboard` | always on | node.nobridge.co itself. |
| Nobridge Finance | container `nobridge-finance` | always on | fin.nobridge.co. |
| Caddy | service `caddy` | always on | TLS + routing for all three domains. |
| CRM frontend overlay | mounted into `twenty-server-1` | always on | Our UI bundle over stock Twenty; the server itself is unmodified. |
| Website sign-ups | **Vercel** (off-VM) | per sign-up | nobridge.co writes an Opportunity into the CRM with `source = SIGN_UPS`, using its own 5-year API token (`.crm-sales-engine/mint_website_token.py`, gitignored output). **The only integration not on the VM** — no probe here can see it, so its card says "not monitored from here"; the real check is filtering Opportunities by Source = Sign Ups. |

**Build pipelines (GitHub Actions, not scheduled — they run when someone pushes or dispatches):** `UI Build` in `VAV-TECH-2/CRM` produces the frontend overlay bundle; `build-image` in `VAV-TECH-2/nobridge-finance` produces the Finance image. Neither rebuilds anything on the server by itself — the artifact still has to be copied across, so the live site can lag the code.

⚠️ **crontab is the easy one to miss.** The CRM backup lives in **azureuser's** crontab (`crontab -l`, *not* `sudo crontab -l`, which is empty) and appears in no systemd listing. It is the only cron line left — the two last-contacted refreshes that used to sit beside it are gone, superseded by the Pipeline Autopilot (verified 2026-08-11). `systemctl list-timers` alone will tell you the CRM backup doesn't exist. Retired and no longer running: **the buy-side / sell-side / fulfillment engines and the Claude MCP connector (2026-08-07)**, `automation-registry-sync`, the Venice/Henry/Saley AI agents, the sales digest, Google Tasks, Google Chat notifications, and the heydeal.co domain (the dashboard lists these too, so their absence is explained rather than mysterious).

**Domain note:** `heydeal.co` was the original domain and was **fully retired 2026-07-05** (no redirects; all old links dead). Any `heydeal.co` reference in a script here is **stale** — the live host is `crm.nobridge.co`.

---

## 3. How the CRM is built & deployed

The backend is **never built from this folder** — production pulls the stock image `twentycrm/twenty:v2.7.3`. Only the **frontend** is customized, and it ships as an overlay:

```
edit twenty/ (branch ui/icon-box-sizing)
      │  git push vt2 ui/icon-box-sizing
      ▼
GitHub VAV-TECH-2/CRM  ──►  Actions: .github/workflows/ui-build.yaml
      │                       (builds twenty-front static bundle only)
      ▼
download bundle artifact  ──►  scp to VM  ──►  deploy/front-build/
      ▼
docker-compose.overlay.yml bind-mounts ./front-build over
   /app/packages/twenty-server/dist/front  ──►  restart twenty-server
      ▼
server entrypoint injects window._env_ (SERVER_URL) into index.html at boot
```

- **Production compose file:** `deploy/docker-compose.overlay.yml` (the plain `docker-compose.yml` is the stock, no-overlay version).
- **Image/DB stay stock.** The overlay is frontend-only. This is deliberate — see [§8 gotchas](#8-operational-recipes--gotchas).
- `deploy/front-build/` does **not** exist in this repo; it is created on the VM at deploy time.

---

## 4. Directory guide

Legend: **LIVE** = used in production now · **HISTORICAL** = one-time job, keep for rollback reference · **STALE** = safe to delete · ⚠️ = touches production / contains secrets.

### `twenty/` — CRM frontend source · LIVE
Full clone of the [twentyhq/twenty](https://github.com/twentyhq/twenty) monorepo.
- **Branch:** `ui/icon-box-sizing` (the production frontend branch; ~20 custom brand/UI commits, tree is clean).
- **Remotes:** `vt2` → `VAV-TECH-2/CRM` (**canonical** since 2026-07-05, runs the CI) · `upstream` → `twentyhq/twenty` · `origin` → `VAV-Technologies/CRM` (⚠️ old org, may 404 — do not rely on it).
- Custom work: Nobridge logo/brand, workspace switcher redesign, "Switch to Nobridge Finance" menu item, an Avatar O(n²) re-render fix (the twenty-icons flood crash).
- **Do not build the backend here.** Node 24 + Yarn 4 only needed if you build the frontend locally instead of via CI.

### `deploy/` — infra & deploy config · LIVE ⚠️
| File | Role |
|---|---|
| `docker-compose.overlay.yml` | **Production** compose (frontend overlay bind-mount). |
| `docker-compose.yml` | Stock compose, no overlay (reference/fallback). |
| `Caddyfile.nobridge-final` | **Current** Caddy config (post-heydeal retirement). |
| `Caddyfile`, `Caddyfile.nobridge-stage1/2`, `Caddyfile.with-finance` | Superseded (migration artifacts / old auth model). |
| `vm-rollback.sh` | ⚠️ Full VM reset — **drops all volumes**, mints new secrets, regenerates compose + Caddy. Destructive; last resort. |
| `draft-cleanup/` | systemd unit + timer for the hourly Gmail draft-ghost sweep (see `.crm-sales-engine/cleanup_draft_messages.py`). Installed at `/etc/systemd/system/crm-draft-cleanup.{service,timer}` on the VM. |
| `finance/` | 22 deploy/migration/audit scripts for the Finance app + `AUDIT-FINDINGS.md`. Key ones: `deploy-finance-image.sh`, `deploy-overlay.sh`, `create-*-table.sh`, `add-invoice-mgmt-columns.sh`. |
| `finance/_artifact/finance-image.tar.gz` | 158 MB pre-built Finance image (Jun 10 — likely stale). |

### `.crm-automations/` — automation registry + ops dashboard source · LIVE ⚠️
- `registry.json` — **mirror** of the live registry at `/opt/heydeal-automation-registry/registry.json` on the VM (13 entries), which is what drives the dashboard's Automations tab. The VM copy is canonical; refresh this one after changing it.
- `registry_sync.py` + `*.service`/`*.timer` — **HISTORICAL.** The 5-min sync that pushed the registry into the CRM's "External Workflows" object; retired 2026-07-04 along with that object. The registry has been hand-maintained since, which is why it had drifted to 6 entries while 15 things were running.
- `dashboard/automation_docs.py` — **the plain-language documentation for everything we run outside the stock CRM**, rendered as the "How it works" tab on each System card: what it does, a flow diagram, what it reads and writes, how to tell when it has broken, and where the source and logs live. 13 entries live (automations with flow diagrams, plus the always-on services), each with what it reads and writes, how to tell when it has broken, and where its source and logs are — plus a list of the retired ones. **Anything registered needs an entry here under the same key** — `/api/docs` reports both cards with no docs and docs for cards that no longer exist, so drift in either direction is visible.
- `clienttype-sync/` — **source of the Company↔board sync** (VM: `/opt/heydeal-clienttype-sync/sync.py`, 2-min timer, shows as "Look-Up Integration" in the CRM). Tagging a company auto-creates its deal on the matching board; **deleting a deal from a board removes that tag from the company within ~2 min (Rule D, added 2026-07-21) so deletes stick** — re-tag >15 min later to re-create. Deploy = `scp sync.py` to the VM path.
- `register_automation.py` — CLI to add/update a registry entry (idempotent; also deployed on the VM at `/opt/heydeal-automation-registry/`). Every entry needs exactly one health probe: `--unit` (systemd), `--container` (Docker), or `--watch` (a glob of the output a crontab job produces, judged on freshness and size — the only honest signal for cron).
- `dashboard/dashboard.py` — **source of the `node.nobridge.co` ops dashboard** (stdlib HTTP server, binds 127.0.0.1:3200; Caddy adds TLS, the app does its own Google sign-in — CRM Admin/Manager only). Deploy = `scp` this file to the VM + restart its service.
- `pipeline-autopilot/` — **source of the hourly autopilot that updates the deals itself** (VM: `/opt/nobridge-pipeline-autopilot/`, `pipeline-autopilot.timer`). Reads the synced email, calendar and Call Intelligence output, works out what the workflow says should follow, and writes stage / dates / owner / where-we-last-left-off / a note. **It takes its rules from `dashboard/workflow_spec.py` at runtime** — the same file `WORKFLOWS.md` and the Workflow tab are generated from — so it cannot drift from the documented process. Layers: `evidence.py` (SQL, read-only), `rules.py` (facts + the validator), `judge.py` (Azure gpt-5-mini, proposes only), `crm.py` (the one write path, REST PATCH), `store.py`/`revert.py` (audit + undo), `preflight.py` (does the spec still match the CRM — run every time, refuses the run if not). Deploy = `./deploy-autopilot.sh [--enable]`. ⚠️ `data/autopilot.db` holds email subjects and bodies and is **gitignored but not disposable** — it is the only record of what changed and the only way to undo it.
- `ai-access/` — **source of the connector that lets Claude and ChatGPT read and change the CRM** (VM: `/opt/nobridge-ai-access/`, service `nobridge-ai-access`, behind `node.nobridge.co/ai/`). Two front doors, one tool registry: `POST /ai/mcp/<token>` speaks MCP for Claude (token in the path — a custom connector cannot send headers) and `POST /ai/tools/<name>` takes a Bearer token for a ChatGPT custom GPT, with `GET /ai/openapi.json` public for the importer. **`context.py` is the point of it**: the boards, every field and its meaning, the workflow stage by stage, the 12 ladders and a `gotchas` section, all generated from the live metadata API and `dashboard/workflow_spec.py`, delivered in the MCP handshake before the AI asks anything. It **imports the autopilot's modules rather than copying them** (`deps.py` → `twclient`, `crm`, `db`, `rules`, `spec`, `store`, `revert`), so there is one CRM client, one validator, one audit trail and one ruleset. Writes go through `rules.validate(..., actor="human")`, need `confirm: true`, and land in `autopilot.db` with `source='ai'` so `revert.py --run N --apply` undoes them. `selfcheck.py` runs as `ExecStartPre` and refuses to start on drift. Tokens: `tokens.py --issue <email> --scope read|write`, sha256 only, plus a live Admin/Manager check on every request. Deploy = `./deploy-ai-access.sh [--enable]`. ⚠️ `data/aiaccess.db` holds token hashes and the request log (which contains tool arguments, so email fragments) — **gitignored, not disposable.**
- `blocklist-guard/` — **source of the `blocklist-guard` VM timer** (see table above): `guard.py` (mirror + sweep), `seed_blocklist.py` (one-time seed from the Instantly export, `domains-seed.txt` = the 125 sending domains as of 2026-07-11), systemd units, `deploy-blocklist-guard.sh`. **To block a new sending domain: add `@thedomain.co` in the CRM as vilca@nobridge.co under Settings → Accounts → Blocklist** — the guard propagates it to everyone and cleans matching records within ~2 min. Remove an entry there to unblock (mirrored copies retire automatically; already-deleted records stay in the trash).

### `.crm-fulfillment/` — fulfillment pipeline tooling · LIVE ⚠️
- `tw.py` — **shared Twenty API client.** Mints a JWT from `APP_SECRET` fetched live over SSH (`docker exec twenty-server-1 printenv APP_SECRET`). WORKSPACE_ID / API_KEY_ID are hardcoded constants here.
- `setup_fields.py`, `setup_relations.py`, `setup_view.py`, `migrate_schema.py` — idempotent schema builders (safe to re-run).
- `import_kmp.py` — ⚠️ imports the KMP prospect workbook (277 rows), resumable via `state.json`, writes rollback manifest `created.json`.
- `_*.py` (e.g. `_introspect_*`, `_views*`, `_wh*`) — scratch/debug utilities; not part of any pipeline.

### `.crm-sales-engine/` — sales-engine SETUP tooling · MIXED ⚠️
> This is **not** the running Sales Engine — that is `Desktop\Sales Engine VM`. This folder holds the one-time setup/migration scripts and prototypes. The pipeline engines it was built for were retired 2026-08-07; these scripts are now historical apart from the ones flagged LIVE below.
- `setup_fields_se.py`, `migrate_stages.py` + `stage_migration_manifest.json`, `finalize_stages.py`, `rollback_stages.py` — the 4→8 stage pipeline migration (HISTORICAL).
- `register_webhook.py` / `delete_webhook.py`, `probe*.py`, `test_*.py` — webhook + query tooling.
- `cleanup_draft_messages.py` — **LIVE** ⚠️ mutates prod. Twenty v2.7.3's incremental Gmail sync (`history.list`) can't exclude drafts, so reply drafts get imported as OUTGOING "sent" messages (one per autosave). This script cross-checks every OUTGOING message against Gmail (DRAFT label or 404 = ghost) and soft-deletes the ghosts, manifest at VM `~/crm-draft-cleanup/cleaned.json`. Dry-run by default; `--apply` to delete. **Must run ON the VM** (it shells into the docker containers locally). Deployed at `/opt/crm-draft-cleanup/`, swept hourly by `crm-draft-cleanup.timer` (units in `deploy/draft-cleanup/`).
- ⚠️ **`engine_twenty_token.txt` — a live, long-lived Twenty API JWT (valid for years).** Real secret. `tw.py` here still points at retired `heydeal.co`.
- 🔒 **Not in git:** `engine_twenty_token.txt`, `test_e2e.py`, `test_reconcile.py`, `oauth_exchange.py` are gitignored (they hold the token and a Google OAuth client secret + refresh tokens). On a fresh clone they arrive via the **secrets bundle** — see [`ONBOARDING.md`](./ONBOARDING.md) §4 and `scripts/make-secrets-bundle.sh`.

### `.crm-migrate/` & `.crm-migrate-seller/` — one-time imports · HISTORICAL
Buyer (42 rows, 2026-06-11) and seller (32 rows, 2026-06-12) workbook → Opportunity imports. `match*.py` + `create.py`, with `resolved.json` and `lastcontact.*` outputs. Keep for rollback reference; do not re-run.

### `.deploy-tmp/` — STALE
Single 158 MB `finance-image.tar.gz` (Jun 10). Deletable.

### `_archive/` — retired code + backups · HISTORICAL ⚠️ SENSITIVE
Retired AI agents (Venice / Henry / Saley) + old sales-engine TypeScript source, backed up 2026-07-04, plus `gpt54-deployment-backup.json`. **The `.zip`/`.tgz` here contain old plaintext credentials** (a Twenty JWT, the now-deleted Azure OpenAI key, retired Chat webhooks, a Postgres password). Because of this, **the whole `CRM` folder should be treated as sensitive in transit** (encrypt the copy; don't put it in a shared/synced location).

---

## 5. Services & accounts

| Service | Account / ID | Used for | CLI |
|---|---|---|---|
| **Azure** | VM `vm-twenty-crm`, RG for the VM | Hosts everything. VM start/stop/deallocate/resize. | `az` |
| **Azure OpenAI** | "mama" account (kept for other projects) | The `gpt-5.4` deployment was **deleted 2026-07-04**; AI digest features are off. | `az` |
| **Google Cloud** | project `crm-system-499720` | **One** OAuth client shared by CRM login + Finance login, and Gmail/Calendar sync into the CRM. | `gcloud` |
| **GitHub** | `VAV-TECH-2/nobridge-crm-ops` (this workspace) + `VAV-TECH-2/CRM` (frontend) + `VAV-TECH-2/nobridge-ops-dashboard` (dashboard) + `VAV-TECH-2/nobridge-finance` (finance) | Canonical repos + CI. Old `VAV-Technologies/*` org repos 404. | `gh` |
| **Supabase** | — | ⚠️ **Decommissioned.** Finance migrated to a local Postgres on the VM (2026-06-04). Any Supabase reference is dead. | — |

---

## 6. Credentials index (paths only — no secret values in this file)

> Per policy, this README **never contains secret values**, only where each lives. Most live in `.env` files on the VM (which do not leave the VM); a few sit inside this folder.

| Credential | Service | Where it lives |
|---|---|---|
| `APP_SECRET` | Twenty JWT signing | VM `/home/azureuser/twenty/.env` (also `docker exec twenty-server-1 printenv APP_SECRET`) |
| `PG_DATABASE_PASSWORD` | Twenty Postgres | VM `/home/azureuser/twenty/.env` |
| `AUTH_GOOGLE_CLIENT_ID` / `_SECRET` | Google OAuth (CRM+Finance login, Gmail/Calendar sync) | VM `/home/azureuser/twenty/.env` — ⚠️ **must be mirrored into the worker service** or Gmail sync silently fails |
| ~~4 MCP scope tokens + `TWENTY_WEBHOOK_SECRET`~~ | **Removed 2026-08-07** with the connector and the engines — no longer in the sales-engine `.env`. | — |
| Finance DB password + agent API token | Finance Postgres, Finance agent/MCP | VM `.env.finance` (nobridge-finance compose project) |
| **`engine_twenty_token.txt`** | Long-lived Twenty API JWT | 🗂️ **In this folder:** `.crm-sales-engine/engine_twenty_token.txt` |
| Old agent creds (Twenty JWT, PG pw, webhooks, Azure key) | mostly retired | 🗂️ **In this folder:** `_archive/ai-agents-*.{zip,tgz}` (plaintext) |
| **VM SSH private key** | SSH to the VM | 💻 **Local machine only:** `~/.ssh/id_rsa` — **does not move with this folder** |
| Azure / GitHub / gcloud CLI auth | Azure, GitHub, GCP | 💻 Local CLI credential stores — re-auth on a new machine |

---

## 7. What does NOT live in this folder

Cloning `nobridge-crm-ops` (plus the two nested repos via `scripts/setup.sh`) gives you everything in this folder — but **you still need these external items**, copied or cloned separately:

| Item | Location | Why it matters |
|---|---|---|
| **Sales Engine (running code)** | `Desktop\Sales Engine VM` | Now runs **call intelligence only** — the buy/sell/fulfillment engines were retired 2026-08-07 and their code is dormant. The rules they enforced are written up as an operating manual in [`WORKFLOWS.md`](./WORKFLOWS.md) — read that rather than the dormant TypeScript. `.crm-sales-engine/` here is only its *setup* scripts. |
| **Finance app source** | `Desktop\Nobridge Finance\nobridge-finance` | The `fin.nobridge.co` app. This folder only has its *deploy* scripts (`deploy/finance/`). |
| **VM SSH key** | `~/.ssh/id_rsa` | The **only** way to reach the VM. Without it nothing here works. |
| **User CLI rules** | `~/CLAUDE.md` | Your global "use the CLI, don't kill processes" instructions for Claude. |
| **Claude's memory** | `~/.claude-work/projects/C--Users-Vilca-Desktop-CRM/memory/` | ~30 accumulated notes (incidents, recipes, gotchas). Path is keyed to the folder path — see below. |

---

## 8. New-machine setup & GitHub team sync

**The full step-by-step (Mac + Windows) lives in [`ONBOARDING.md`](./ONBOARDING.md).** Summary of the model:

**Three repos, one folder.** The root repo ignores the nested two; each syncs independently:

| Path | GitHub repo | Canonical remote |
|---|---|---|
| `CRM/` (this folder) | `VAV-TECH-2/nobridge-crm-ops` (public) | `origin` |
| `CRM/twenty/` | `VAV-TECH-2/CRM` (public, runs the `ui-build.yaml` CI) | `vt2` |
| `CRM/.crm-automations/dashboard/` | `VAV-TECH-2/nobridge-ops-dashboard` (private) | `origin` |

**Daily sync:** pull all three at session start, push what you changed at session end (`git pull` in root; `git -C twenty pull vt2 ui/icon-box-sizing`; `git -C .crm-automations/dashboard pull`). Small team, trunk-based — pull before push, coordinate prod deploys in chat.

**Secrets never ride in git.** The public repo gitignores the token + credential-bearing scripts (§4). They move via a password-protected zip: `scripts/make-secrets-bundle.sh` builds it, `scripts/restore-secrets.{sh,ps1}` restores it. Share zip and password over different channels.

**Cross-OS:** line endings are pinned by `.gitattributes` (LF everywhere, CRLF only for `*.ps1`) — don't set `core.autocrlf`. Windows needs `git config --global core.longpaths true` and runs all `.sh` scripts from **Git Bash**. Expect (and ignore) the harmless `Price/`↔`price/` case-collision warning when cloning `twenty/` — upstream artifact.

Setup checklist (details in ONBOARDING.md):

1. **Clone** `nobridge-crm-ops` to `Desktop/Nobridge Software/CRM`, then run `scripts/setup.sh` (or `scripts\setup.ps1`) — clones `twenty/` + `dashboard/` into place.
2. **Restore secrets** from the bundle (`scripts/restore-secrets.sh <zip>`), and copy the external items from §7 (SSH key, sales-engine-vm, Finance source).
3. **Claude memory dir is path-keyed** to this folder's absolute path — on a new machine, re-key the memory folder to the new path or Claude won't auto-load it.
4. **Install & authenticate CLIs:**
   - `az login` (Azure) · `gh auth login` (GitHub) · `gcloud auth login` (only if editing Google/OAuth)
   - OpenSSH client (for `ssh`/`scp` to the VM)
   - Python 3.13 (the `.crm-*` scripts) — install `requests`, `pyjwt`, `openpyxl` as needed
   - Node 24 + Yarn 4 **only** if building the frontend locally (normally CI does it)
   - Docker Desktop **only** if building images locally (normally not needed)
5. **Verify access:**
   ```bash
   ssh azureuser@20.189.126.94 "echo ok && sudo docker ps --format '{{.Names}}'"
   gh repo view VAV-TECH-2/CRM
   curl -I https://crm.nobridge.co && curl -I https://fin.nobridge.co && curl -I https://node.nobridge.co
   ```

---

## 9. Operational recipes & gotchas

**Stability policy (most important):** the owner prefers **stock images, no forks of the backend, single workspace**, after losing hours to crashes. Do not "improve" the architecture without being asked.

- ⛔ **Never boot the `latest` (or any newer) Twenty image.** Booting it even once migrates the DB schema forward; the pinned `v2.7.3` image then crashes on start (Postgres error `42703`, missing column). **Stay on `v2.7.3`.**
- ⛔ **Never `docker build` on the VM without swap.** An 8 GB VM OOM-wedges during build. Recovery: `az vm deallocate` then `az vm start`. (Frontend ships via CI, so you rarely build on the VM anyway.)
- 📎 **PowerShell → SSH stdin adds a UTF-8 BOM.** Piping a script into `ssh ... 'bash -s'` corrupts the first line. **Write the script to a file and `scp` it**, then run it.
- ✉️ **No SMTP.** `EMAIL_DRIVER` is unset, so invites and password-reset emails are **not sent**. To invite someone, build the link manually from `core.appToken` + `workspace.inviteHash`.
- 🔑 **Gmail OAuth dies every ~7 days** if the Google consent screen is in "Testing." Fix = set the OAuth app to Internal / Publish to Production (Console only), then reconnect the account.
- 🗄️ **Messaging data is SPLIT between the two schemas** in v2.7.3, and this line used to say the opposite. `message`, `messageParticipant`, `messageThread`, `messageChannelMessageAssociation`, `calendarEvent` and `calendarEventParticipant` are in `workspace_4cukon…` and are **populated** (6,860 messages, 11,804 participant links) — the two nightly last-contact jobs and `pipeline-autopilot` all read them there. Only `messageChannel`, `messageFolder` and `connectedAccount` are in `core`. Visibility is plain row data — a direct `UPDATE` takes effect on the next read.
- 🧭 **Direction is not on the message.** `messageChannelMessageAssociation.direction` looks authoritative but 2,229 of 6,860 messages carry **both** INCOMING and OUTGOING, because a mail sent by one staff member and copied to another is outgoing in one channel and incoming in the other. The reliable test is whether the `role='from'` participant's handle is `@nobridge.co`.
- 🖼️ **Workspace logo:** the Settings → General uploader works natively. **Do not** hardcode the brand Avatar in the frontend — that override blocked uploads once and was reverted.
- 📊 **Ops dashboard deploy** = `scp .crm-automations/dashboard/dashboard.py` to the VM + restart its service. It reads live from the sales-engine `.env`. Auth is app-level Google sign-in (CRM Admin/Manager only, like Finance); secrets live in `/opt/heydeal-automations-dashboard/dashboard-auth.env`, (re)written by `deploy/dashboard/wire-dashboard-auth.sh`. To let someone in: give them Admin/Manager in the CRM, or add their email to `FULL_ACCESS_EMAILS`.
- 🤖 **Claude's own Google MCP account is `vilca@understoryagency.com`, NOT Nobridge.** It has no Nobridge deal mail and no Calendar scope. For "last contact" data, query the CRM's synced `message`/`messageParticipant` tables instead.
- 📧 **Cold-email sending domains are blocklisted in the CRM** (125 lookalike domains: asiadeals.co, equitydeals.co, nobridge*.co/.com/.info, …). Emails involving them do **not** sync and matching Companies/People are auto-removed by the `blocklist-guard` timer. **Reply workflow:** when a prospect replies to a cold inbox, forward it to your `@nobridge.co` mailbox (the forward itself won't appear in the CRM — expected), then **compose a brand-new email to the prospect's real address** quoting the reply below. That new thread syncs and registers the prospect's own company/person (e.g. apple.com), never the sending domain. The master list is vilca's blocklist under Settings → Accounts → Blocklist.

---

## 10. History / glossary (so old references don't mislead)

- **2026-08-11** — **you can talk to the CRM now: `ai-access`.** A connector at `node.nobridge.co/ai/` (service `nobridge-ai-access`, source [`.crm-automations/ai-access/`](./.crm-automations/ai-access/)) that lets **Claude** (MCP, token in the URL path) or a **ChatGPT custom GPT** (OpenAPI Actions, Bearer) read the pipeline and change it — 8 read tools and 8 write tools from one registry rendered two ways. **This is the deliberate replacement for the ops MCP connector retired on 2026-08-07**, and the difference is `context.py`: a context engine that hands the AI the five boards, every field and its meaning, the workflow stage by stage, the 12 chase ladders and a `gotchas` section *before* it answers anything, all generated from the live metadata API and `dashboard/workflow_spec.py`. The old connector could set any field and understood none of it; old `/mcp/<token>` URLs still 404. Writes go through the autopilot's own `rules.validate(..., actor="human")` — so a deal still cannot skip a stage, move backwards, leave Closed or close without a verdict — need `confirm: true` (the diff is shown first, in the conversation), and land in `autopilot.db` with `source='ai'` so `revert.py --run N --apply` undoes them. Per-person tokens, sha256 only, plus a live Admin/Manager check on every request. The dashboard gained an **AI Access** tab (its 7th) showing who holds a token, what was asked, and what changed with its undo command. Two bugs were fixed on the way: `rules.py` was writing a stage move it had just refused for having no verdict, and the dashboard's `/api/autopilot` was reading `?run=12` as run 1. **No business data was changed** beyond one commentary field written and reverted as a test.
- **2026-08-11** — **the CRM began updating itself: `pipeline-autopilot`** (hourly timer). Reads the synced email, calendar and Call Intelligence output and writes stage, contact dates, next owner, next action due, meeting outcome, qualified, owner, "where we last left off" and a note. Rules read from `workflow_spec.py` at runtime; guardrailed and reversible. Full account in [`CLAUDE.md`](./CLAUDE.md).
- **2026-08-09** — **the v2 workflow was applied to the live CRM**: 9/10/9 stages, 135 steps, 12 named loops, 45 new fields, 449 records re-staged, 487 records intact. `WORKFLOWS.md` now describes the live CRM and is generated from `workflow_spec.py`. Runbook: [`.crm-migrate-v2/RUNBOOK.md`](./.crm-migrate-v2/RUNBOOK.md).
- **2026-08-08** — **the pipeline workflow was written down and bound to the CRM.** [`WORKFLOWS.md`](./WORKFLOWS.md) stopped being an epitaph for the retired engines and became the **operating manual**: four status axes (Position `stage` · Pulse `progressType` · Meeting `meetingOutcome` · Verdict `finalDecision`/`outcome`), every engine sub-state re-expressed as a predicate over visible fields, a field dictionary for all five boards, and the **promotion steps** (`P01`–`P07`, `FP01`–`FP06`) that say when a deal earns its next stage — which nothing had ever recorded. The same content is in-product on the dashboard's Workflows tab: each of the 42 steps now carries its board position, the CRM state that triggers it, the fields it writes, and whether it is automatic, approved on Calls, or done by hand; the charts label every node with CRM state and draw the call-note step (`X01`). **Documentation only — no CRM data or metadata was changed.** Three things were left as known work: the `finalDecision` field is being used as a live status on 40 buy deals (blank should mean open), the boards have drifted apart (Buy ends `Completed`/`Skipped` and carries 7 verdicts; Sell and Other end `Closed Won` and carry 3; only Sell has `engagementStatus` and `nextReachOutAt`), and the clock fields cleared in the retirement below are still empty, so Pulse cannot yet be derived.
- **2026-08-07** — **the buy-side, sell-side and fulfillment rules engines were retired**, along with the Claude MCP connector. They matched on stage + timestamps with no understanding of the conversation, so the tasks they raised were noise. What changed: the three engines no longer start (their code stays in `Desktop\Sales Engine VM`, dormant, as the record of the rules); the engine's state DB was archived then wiped; **440 engine-created tasks were deleted from the CRM**; the dashboard lost its Overview, Pipeline and Access tabs; `node.nobridge.co/mcp/*` returns 404 and the 4 scope tokens are gone. **No business data was touched** — every deal, board, company, contact, note and tag is exactly as it was. A follow-up pass the same day did clear the **150 field values the engines themselves had written** (`escalatedAt`, `repliedAt`, the `*SentAt` stamps, `nextReachOutAt`, and the 16 `GHOSTED` / 5 `HELD_OFF` marks the sell cadence applied) — machine output, not anyone's judgement. `meetingOutcome` was kept: it is derived from real calendar events. Per-record prior values are in `engine_field_footprints.tsv` alongside the backups, since Twenty records no per-field authorship. The **rules** outlived the engines — see the 2026-08-08 entry above and [`WORKFLOWS.md`](./WORKFLOWS.md). Retirement backups (CRM dump, engine DB, JSON exports, configs) live **outside this repo** at `Desktop/Nobridge Software/_backups/20260807-preremoval/` and on the VM at `~/_archive/20260807-preremoval/`.
- **2026-07-06** — `node.nobridge.co` ops dashboard moved off Caddy basic-auth to app-level Google sign-in + CRM role check (Admin/Manager only), mirroring Finance; the shared OAuth client gained a `node.nobridge.co/api/auth/google/callback` redirect URI.
- **2026-07-05** — `heydeal.co` fully retired → `crm/fin/node.nobridge.co`. One OAuth client now serves CRM + Finance + the node dashboard. All old `heydeal.co` links are dead.
- **2026-07-04** — AI agents (Venice / Henry / Saley) and the `gpt-5.4` deployment removed; backups in `_archive/`.
- **2026-06-22** — deals split into 5 opportunity objects (buy / sell / other / fulfillment / networking), driven by the Client Type sync timer.
- **2026-06-18** — the "Castudio" project was decommissioned on Azure (unrelated to this system; no shared DB ever existed).
- **2026-06-04** — Finance migrated off Supabase to a local `finance-db` Postgres on the VM. Supabase is unused.

---

*If you're a Claude agent reading this: the deepest operational detail is in the memory dir (§7). This README is the map; the memory notes are the field journal. When in doubt about a live system, verify against the VM (`ssh`) or the running site before acting — some notes reflect what was true when written.*
