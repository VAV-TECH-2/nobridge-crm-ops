# AI Access — the CRM's brain, reachable from a chat window

The CRM updates itself (`../pipeline-autopilot/`). This is the other half: **asking it things, and
telling it to change things**, from Claude or a ChatGPT custom GPT, without opening the CRM.

- *"Where is the Naluri deal and what's next?"* → board, stage, 7 of 9, days there, which chase
  ladder is running and which touch is next, the workflow steps for that stage, last email each way,
  next meeting, last call.
- *"Two new leads came in — put them on buy-side and give them to Fadil."* → company created, tagged,
  the deal appears on the right board at the right first stage, owner set. Reversible.

Live since 2026-08-11 at `https://node.nobridge.co/ai/`.

## Why this is not the connector that was retired

The ops MCP connector was switched off on 2026-08-07 because it exposed raw CRM tools — `crm_update`,
`crm_graphql`, a field whitelist — and understood nothing about what a stage meant. It produced
confident nonsense.

The difference here is **`context.py`**: before answering anything, the AI is handed how the five
boards work, what every field means, the workflow stage by stage, the twelve chase ladders, and the
list of things that are true but surprising. All of it is generated from the live metadata API and
from `../dashboard/workflow_spec.py` — the same file `WORKFLOWS.md` is printed from and the autopilot
obeys — so it cannot describe rules nobody is following.

And writes go through **the autopilot's own validator**, so the connector cannot be more permissive
than the automation by accident.

## Nothing here is a second copy

```
context.py  tools.py  guard.py  server.py  auth.py       ← this folder
                    │
        imports at runtime, never copies
                    ▼
  ../pipeline-autopilot/  twclient · crm · db · rules · spec · bizdays · store · revert
                    │
                    ▼
  ../dashboard/workflow_spec.py   ← one ruleset, shared with WORKFLOWS.md and the autopilot
```

One CRM client, one validator, one audit trail, one ruleset. `deps.py` puts the autopilot on
`sys.path`; the service will not start if it is not deployed.

## The 16 tools

**Read** — `crm_context` (the manual, by section) · `find_record` · `get_deal` (the workhorse) ·
`whats_next` · `pipeline_summary` · `explain_workflow` · `recent_activity` · `list_members`

**Write** — `update_deal` · `set_stage` · `stamp_step` · `set_verdict` · `log_note` ·
`create_company` · `tag_company` · `undo`

Every write tool is a **two-call tool**: without `confirm: true` it returns the exact diff it would
apply and changes nothing. The confirmation happens in the conversation, where the person is.

`stamp_step` is the one worth knowing about. Say *"I sent the proposal"* and it applies exactly the
fields that workflow step defines — the sent-at timestamp, who owns it next, and the follow-up date
counted from the right anchor field. Setting the timestamp by hand gets the date right and the
follow-up ladder wrong.

## What always refuses

Structural rules come from `rules.validate(..., actor="human")` and do not bend:

- one stage forward, or straight to `Closed` — never backwards, never skipping
- never out of `CLOSED` (re-engaging a closed deal opens a *new* deal, ladder L10)
- never close without a verdict in the same change
- only fields a workflow step authorises at that stage, plus free-text commentary
- every value coerced against the live options on *that* board

What *does* bend for a person: the confidence bars (there is nothing to infer when somebody has said
what they want) and the one-stage-move-per-day pacing cap — which yields, loudly, and records the
override.

## Setup

```sh
./deploy-ai-access.sh --enable        # from Git Bash on Windows, never PowerShell

# a token per person; printed once, only the hash is stored
ssh azureuser@20.189.126.94 'cd /opt/nobridge-ai-access && sudo python3 tokens.py --issue you@nobridge.co --scope write'
```

- **Claude** — Settings → Connectors → Add custom connector → paste the `/ai/mcp/<token>` URL. No
  sign-in step: the token *is* the credential, so treat the URL as a password.
- **ChatGPT** — create a GPT → Actions → import `https://node.nobridge.co/ai/openapi.json` → auth
  API Key / Bearer → then **paste the instruction block from the AI Access tab into the GPT's
  Instructions**. ChatGPT has no channel to receive the context automatically; that paste is what
  gives it the brain, and it goes stale when the workflow changes (the tab shows a fingerprint so you
  can tell). Claude re-reads the context on every connection.

Access needs the token *and* an Admin or Manager role in the CRM, checked live on every request —
remove somebody there and this goes with it. Scope is `read` or `write`, optionally limited to
certain boards.

## Running it

```sh
python3 selfcheck.py                       # refuses on anything that would make it answer wrongly
python3 cli.py --list                      # every tool, callable from a terminal
python3 cli.py get_deal '{"company":"Naluri"}'
python3 context.py > ../../AI-CONTEXT.md   # regenerate the reviewable copy of the context pack
python3 tokens.py --list                   # who holds what
```

`selfcheck.py` runs as `ExecStartPre`, so a blocker means the unit does not come up. That is
deliberate: a connector serving a stale ruleset is worse than one that is down, because nothing looks
wrong. It is what caught the first deploy attempt, where the VM's autopilot copy predated a function
this needs.

## Things to know

- **`data/aiaccess.db` is gitignored and is not disposable.** It holds token hashes and the request
  log, and the log contains tool arguments, which contain fragments of email. The root repo is
  public.
- **Deal writes are not in that database.** They go into the autopilot's `autopilot.db` with the old
  value and `source='ai'`, which is why `revert.py --run N --apply` undoes a chat-driven change with
  no new tooling. Two writers on one SQLite file, WAL, and an AI stage move spends that deal's daily
  allowance so the hourly run will not move it again.
- **Company creates and tags are audited but not auto-revertible.** Revert works by PATCHing a board
  record back and a company is not one; and removing a `clientType` tag does not delete the deal the
  sync already created, so that cleanup is a person's job. The tools say so in their results.
- **It never sends email.** If the same AI holds your mailbox it can send there and stamp the CRM
  here — that is the real unlock — but they are two separate acts.
- **Cold outreach is invisible**, same blind spot as the autopilot: Instantly's sending domains never
  sync.
- **One lock, one tool call at a time.** `store.py` holds a single connection, `twclient` throttles
  through a module global, `crm.py` caches metadata in module state. Serialising also keeps this
  inside Twenty's 100-request-per-60-second budget, which is per workspace and shared with the
  autopilot, clienttype-sync and blocklist-guard.
- **An unknown or revoked token gets a bare 404**, never a 401. A 401 confirms the endpoint exists.
- **`/.well-known/oauth-*` and `/register` must 404.** MCP clients probe those before connecting and
  read anything else as "sign in here" — the failure `fin.nobridge.co` hit on 2026-07-28. Caddy
  answers them 404 for this host and so does this server.

## A spec problem this surfaced, and how it was fixed

`sets` in `workflow_spec.py` does double duty: it is both *what a step writes* and *the allowlist of
fields writable at that stage* (`rules.allowed_fields()` builds from its keys). So a stage has to
authorise every field any event in it might touch — including events happening **later** than the step
being described. Two of those were written as `now`, which claims the step stamps them:

| step | prose said | `sets` also claimed |
|---|---|---|
| B74/S74 Out for signature | `Signature Sent At = now · Contract Signed At **on return**` | `contractSignedAt: now` |
| B32/B52/S32/S52 Deliver the … | `Strategy Sent At = now` (no mention) | `escalatedAt: now` |

Applied literally, stamping "out for signature" would have marked the contract **signed**.

**Fixed 2026-08-12 in the spec, where it belonged**, by adding a seventh value kind: **`"allow"`** —
*writable at this stage, but not written by this step*. That is the thing `sets` previously could not
say. Because `allowed_fields()` reads keys only, the allowlist half is preserved for free: a person or
this connector can still set those fields deliberately, and `stamp_step` no longer touches them.

Two traps were handled on the way, both worth knowing if a kind is ever added again:

- **`judge._writable_text` is a denylist**, so a new kind is *shown* to the model by default and would
  pass validation (the field is in the allowlist by definition). `"allow"` had to be added to that
  filter, which is what makes this a zero-behaviour-change fix rather than the opposite of one.
- **`preflight.KIND_TYPES.get(kind)` returning `None` silently skips the type check**, and is
  indistinguishable from the deliberate `None` used by `judge`/`clear`. `"allow": None` is written out
  explicitly for that reason.

`guard.py` no longer parses prose — the heuristic that stood in for this is gone. `preflight.py` now
carries the check instead, as a warning: *a step that stamps a field its own description does not
mention probably means `allow`*. It is gated on `now` only, because the prose is deliberately an
incomplete description — a step's due date is declared in its `owner` column, not in `writes`, which
is precisely why prose was the wrong thing for the write path to depend on.
