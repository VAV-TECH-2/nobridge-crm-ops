# Pipeline Autopilot

Reads the email, meetings and call notes the CRM already syncs, works out what the documented
workflow says should follow, and writes it onto the deal. Hourly, on the VM.

Its rules are **not** in this folder. They are read at runtime from
`../dashboard/workflow_spec.py` — the same file `CRM/WORKFLOWS.md` and the dashboard's Workflow tab
are generated from. Edit the spec, deploy it, and behaviour changes with no code change. That is the
point: the previous arrangement had four hand-kept copies of one ruleset and they disagreed.

## Everyday commands

```bash
python3 autopilot.py                      # DRY RUN across every board. Writes nothing.
python3 autopilot.py --apply              # execute
python3 autopilot.py --board fulfillment --limit 20
python3 autopilot.py --record <uuid> -v   # one record: its evidence, the prompt, the raw reply
python3 autopilot.py --no-judge           # deterministic layer only, no model calls
python3 preflight.py                      # do the rules still match the CRM? (exit 1 = no)
python3 revert.py --list                  # recent runs
python3 revert.py --run 12 --apply        # put everything run 12 wrote back
```

From a laptop everything works read-only against production over SSH; `--apply` writes for real.
On the VM it uses the local socket and the engine `.env`. Mode is detected, not configured.

## The three layers

| File | Does |
|---|---|
| `evidence.py` | **What happened.** SQL over `message` / `messageParticipant` / `calendarEvent`, plus Call Intelligence's `call_summaries` read-only. Read-only by construction — every query runs in a `SET TRANSACTION READ ONLY` block. |
| `rules.py` | **What follows.** `derive()` computes the facts (last contact, who owes the next move, loop timing). `validate()` clamps everything judgement proposes back inside the rules. |
| `judge.py` | **What it means.** Azure `gpt-5-mini`, prompt generated from the spec at request time. Proposes only; holds no CRM credentials and has no write path. |

`crm.py` is the single write path (REST `PATCH`, plus GraphQL for notes). `store.py` records every
run, decision and field write. `revert.py` replays old values back. `preflight.py` checks the spec
against the live CRM and is run before every pass.

## Guardrails

- One stage forward, or straight to Closed. Never out of Closed — re-engagement opens a *new* deal.
- Never close without a verdict. A Closed deal with no Final Decision is the hanging state the v2
  migration existed to remove.
- One stage move per deal per day, however many runs happen in between. A move that was reverted
  does not count against that.
- Circuit breaker: a run that would move more than 25 records, or more than 15% of a sample of at
  least 20, aborts and writes nothing.
- Confidence floors: 0.75 to move a stage, 0.60 for a field, 0.90 for Do Not Contact — which also
  has to quote the sentence that asked for it.
- The watermark advances only on a zero-error pass, and never on a dry run.

## What it deliberately does not do

- **Send email.** Every "send the X" step in the spec is still a person's job; this stamps that it
  happened and works out when the next touch is due.
- **See cold outreach.** Instantly's sending domains never sync into the CRM, so for the three cold
  ladders (L1, L11, L12) it knows about replies but cannot confirm a touch went out. Timing comes
  from the anchor field instead.
- **Touch networking stages.** `_networking` has no pipeline in the spec, so it gets activity fields
  and notes only.
- **Undo itself from the dashboard.** The Autopilot tab is read-only; reverting is this CLI. Giving
  the dashboard a write path would make it a second thing that can change a deal.

## Deploy

```bash
./deploy-autopilot.sh              # copy code + units, run preflight
./deploy-autopilot.sh --dry-once   # ...and one dry pass on the VM
./deploy-autopilot.sh --enable     # ...and enable the hourly timer
```

The dashboard side (`workflow_spec.py`, `automation_docs.py`, `dashboard.py`) deploys separately —
`scp` to `/opt/heydeal-automations-dashboard/` and restart the service. **Deploy the spec whenever
you change it**, or preflight will correctly refuse to run against a stale deployed copy.

## When something looks wrong

```bash
tail -50 /home/azureuser/pipeline-autopilot.log
sudo journalctl -u pipeline-autopilot -n 100 --no-pager
systemctl list-timers pipeline-autopilot.timer
```

and node.nobridge.co → **Autopilot** for every decision with the reason it recorded.

⚠️ `data/autopilot.db` holds email subjects and bodies. This repo is **public**; the directory is
gitignored. It is also the only record of what changed and the only way to undo it — do not delete
it to tidy up.
