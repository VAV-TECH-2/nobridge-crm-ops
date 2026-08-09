# v2 migration runbook

**For whoever runs this — human or agent.** Read it before touching anything. It is the only
document in this folder; `README.md` is a pointer to it, deliberately, because two files
describing one migration is how they start disagreeing.

*Written 2026-08-09. Every number below was read from the live CRM that day.*

---

## 1. State of play

## ✅ APPLIED IN FULL — 2026-08-09, 14:26–15:02

**The CRM is on v2.** All seven steps ran; every one is a clean no-op on re-run.

| Step | State |
|---|---|
| `01_add_fields` | ✅ 45 fields created across the four boards |
| `02_stage_options` | ✅ v2 stages added (buy +7, other +7, sell +8, fulfillment +5) — *after* one failed attempt, §5.4 |
| `03_verdicts` | ✅ Final Decision at 8 options on all three opportunity boards |
| `04_map_stages` | ✅ **449** records re-staged; 27 stageless fulfillment records left alone |
| `05_verify` | ✅ **PASS** — 487 of 487 on v2 stages, re-run after 06 and 07 |
| `06_remove_old` | ✅ 19 retired options removed — *after* one failed attempt, §5.5 |
| `07_relabel_stages` | ✅ labels + column order matched to the spec (§5.6) — a step that did not exist when this was written |

The boards now read exactly as `python3 schema.py` describes them:

```
buy / other  Lead · Qualified · Intro Meeting · Strategy · Strategy Review · Revamps · Pitch · Negotiation · Closed
sell         Target · Contacted · Engaged · Intro Meeting · Strategy · Strategy Review · Revamps · Pitch · Negotiation · Closed
fulfillment  Approach · Engaged · Meeting 1 · NDA · Meeting 2 · Due Diligence · Meeting 3 · Offer Expected · Closed
```

**`clienttype-sync` was broken by this and has been fixed** — same afternoon, see §9. It created
records at `NEW_LEAD` / `REACHED_OUT`, which `06` removed, so tagging a company produced nothing.

**`stage` no longer has a default** on any board (it was `'NEW_LEAD'` on three). A record created
without an explicit stage arrives with no stage and will not appear on the kanban until one is set.
Nothing replaced the default deliberately: see §5.5.

**`Crash Out / DNC` holds no records.** Checked against the database including soft-deleted rows on
2026-08-09: `engagementStatus` on sell is `IN_DISCUSSIONS_SCHEDULED` ×2, `AWAITING_REPLY` ×1, null
×32, and `CRASH_OUT_DNC` **×0**. So §4's second gate has nothing left to protect *today* and the
field can be retired without migrating anything. Re-run that count before you do — it is a snapshot,
and the field is still the only place that request can be recorded until the verdict gets used.

**The pre-migration baseline was** `c382bb69fe726cd82011cc3a4778597537d07c928cc43e262bb1abf00f7bcee5`
— the hash of the full schema plus every record's stage, and, until 14:26 on 2026-08-09, the proof
that no script had ever written anything. `_snapshot.py` **will no longer match it**, and that is
now expected rather than alarming. It remains useful for a different question: take a hash before
and after a *dry* run and they must still agree.

**The CRM boards are on the OLD six stages.** `CRM/WORKFLOWS.md` and both Workflow tabs describe
v2, which does not exist in the CRM yet. `CRM/_archive/WORKFLOWS-pre-v2.md` is what is live.

## 2. Ground rules

1. **This is production.** `crm.nobridge.co`, 487 real records, a live team.
2. **Dry run first, every time.** Every script prints exactly what it would do.
3. **`--apply` only when the user has asked for that specific step.** Not "the migration" —
   the step. They are separately reversible, and one of them is not reversible at all.
4. **Never chain them.** Read the output of each before starting the next.
5. Target schema is **derived** from `.crm-automations/dashboard/workflow_spec.py`. If a stage
   name looks wrong, fix the spec and regenerate — do not hand-edit `schema.py`.

## 3. The six scripts

```sh
cd .crm-migrate-v2
python3 01_add_fields.py            # look
python3 01_add_fields.py --apply    # then do
```

| # | Script | Mutates | Reversible? |
|---|---|---|---|
| 1 | `01_add_fields.py` | Creates 16 fields | Yes — delete them (drops their data) |
| 2 | `02_stage_options.py` | **Adds** new stage options, keeps old | Yes — manifest restores the option list |
| 3 | `03_verdicts.py` | Final Decision → 8 options | Yes — manifest |
| 4 | `04_map_stages.py` | Every record's stage | Yes — manifest holds each record's old stage |
| 5 | `05_verify.py` | *nothing* — read-only gate | n/a |
| 6 | `06_remove_old.py` | **Deletes** old stage options, clears `stage`'s default | **NO** |
| 7 | `07_relabel_stages.py` | Option labels + positions (no values) | Yes — manifest |

### What a clean run looks like

- **01** — 45 creations across 4 objects. Fields already present are reported `exists` and
  skipped, so a half-finished run is resumed by running it again.
- **02** — buy +7, other +7, sell +8, fulfillment +5. Fulfillment adds fewer because
  `MEETING_1`, `NDA`, `MEETING_2` and `MEETING_3` already match.
- **03** — buy +1, sell +5, other +5.
- **04** — **449** records move: buy 92, sell 35, other 5, fulfillment 317. Everything else is
  already on a value the new set keeps (7 buy on `STRATEGY`; 1 `MEETING_1`, 1 `MEETING_2` and 2
  `NDA` on fulfillment), or has no stage at all (27, see §6).
  This said **131** until 2026-08-09, which counted buy + sell + other and silently dropped
  fulfillment's 317 — while §6 of this same document described those 317 in detail. If you are
  reconciling counts, §6 was the one telling the truth. The remaining record of the 449 is the
  stageless buy record §6 used to mention: someone set it to `NEW_LEAD` by hand on 2026-08-09,
  which is why buy leads read 48 rather than 47 and why only 27 records now lack a stage.
- **05** — must print `PASS` and write a `VERIFIED` file.
- **06** — removes what 05 proved is unused.

## 4. The two gates

**`05` before `06`.** `06` refuses to start without a `VERIFIED` file. Removing an option while a
record still points at it takes that record's stage with it, and `rollback.py` cannot get it back.
That asymmetry is the whole reason `06` is a separate script rather than the tail of `02`.

**`03` before any retirement of Sell's Engagement Status.** `Crash Out / DNC` there is currently
the only field in the entire CRM that can record a company asking not to be contacted. Retiring it
before a `Do Not Contact` verdict exists destroys that, irreversibly — and it is the one status
here with a consequence outside the CRM. (Nothing in this folder retires it; see §7.)

## 5. DO NOT UNDO — three bugs the dry runs already caught

Each looks like a needless complication. Each was a real, silent bug found by dry-running against
the live schema. If you "simplify" one back, it will fail quietly rather than loudly.

**1 · Fields come from the `fields` root query, not nested in `objects`.**
`runner.Run.objects()` fetches fields per object with `_FLD_Q` and a `FieldFilter`. The nested
form — `objects { fields { … } }` — returns **3 fields instead of 33**, with no error and no
pagination warning. `01_add_fields` would have seen an almost-empty field list and created 16
duplicate columns on every board.

**2 · Fulfillment's stage values are not derivable from its labels.**
`schema.STAGE_MAP["fulfillment"]` hardcodes `REACHED_OUT` (label: *Reached Out / Teaser*) and
`DUE_DILIGENCE_VDR` (label: *Due Diligence*), confirmed by introspection. Deriving them from the
labels — as `_value()` does for the *target* stages — matched nothing, and all 348 records were
silently reported as unmapped and left where they were.

**3 · REST paging takes the opaque cursor, not a record id.**
`_all()` in `04` and `05` follows `pageInfo.endCursor`. Passing a record id to `starting_after`
works on the 5-, 35- and 99-record boards and returns `400 Invalid cursor` on the 348-record one —
so it looks correct until the one board that matters.

**4 · Generated option ids must be hex — `schema.SIDE_HEX`, not the side's first letter.**
Found the hard way on 2026-08-09, by the first `--apply` rather than by any dry run. The last group
of a UUID is hexadecimal. `stages_for()` originally built ids as `…-8000-{side[:1]}{i:011d}`, and
`b` (buy) and `f` (fulfillment) *are* hex digits, so those two boards were accepted — but `s`
(sell) is not, and the server rejected all eight sell options at once:

```
METADATA_VALIDATION_FAILED — "Option id is invalid", value "40404040-0000-4000-8000-s00000000000"
```

`SIDE_HEX = {"buy": "b", "sell": "a", "fulfillment": "f"}` fixes it. **`buy` must keep `b`** — those
ids are already live in the CRM. Do not "tidy" this back into deriving the char from the name.

**5 · `06` must clear `stage`'s default in the SAME mutation that removes options.**
The second failure of the same kind, and it stopped `06` dead on its first apply:

```
METADATA_VALIDATION_FAILED — "Default value \"'NEW_LEAD'\" must be one of the option values"
```

`stage` defaulted to `'NEW_LEAD'` on buy, sell and other — a value `06` removes — so the server
rejected the whole update. Three of four boards would have failed; only `fulfillment`, which had no
default, would have gone through. `06` now sends `defaultValue: None` alongside the trimmed option
list, atomically per board, and records the old default under `stage_default_before` in its
manifest. It failed *safe*: the update is all-or-nothing, so nothing was removed.

The default was **cleared** rather than repointed at `LEAD`/`TARGET`. Consequence, by choice: a
record created with no explicit stage now has no stage. It does not silently file itself under Lead.

**6 · The kept options end up in the wrong ORDER, and nothing in `01`–`06` fixes it.**
`02` appends new options after the existing ones; `06` then removes the old ones out of the middle.
The stages v2 *keeps* — `STRATEGY` and `REVAMPS` on buy/sell/other, `MEETING_1/2/3` and `NDA` on
fulfillment — therefore keep their original low positions and sort to the front. Buy rendered as
`Strategy · Revamps · Lead · Qualified · …`: every column present, every one in the wrong place, on
all four boards. `02` also never relabels a value it did not add, so `STRATEGY` and `REVAMPS` still
read `Stage 3 · Strategy / Value Creation` and `Stage 5 · Revamps`.

`07_relabel_stages.py` fixes both from the spec, matched on value. Run it after `06`. It leaves
colour alone deliberately — see the note in the script.

The general lesson is worth more than any of these: **a dry run cannot validate anything the server
only checks on write, and it cannot see a state that only exists after an earlier step ran.** It
never POSTs. §1's baseline hash proves the scripts do not *change* the CRM without `--apply`; it was
never evidence that the mutations would be *accepted*, and bugs 4, 5 and 6 were all invisible until
something had already been applied.

## 6. Known findings — real, and not bugs

**The two conditional splits collapse.** `04` splits Stage 1 on whether outreach was sent and
whether they replied. Those fields are empty on every record — the retired engine's values were
cleared on 2026-08-07 — so:

- all **48** buy leads → **Lead**, none → Qualified *(47 when this was written; see §3)*
- all **5** other leads → **Lead**, none → Qualified
- all **317** fulfillment records → **Approach**, none → Engaged
- the single sell lead → **Target**

The new stages are created, but nothing is actually distinguished yet. `04` prints this on every
run. It is expected, and it means the Lead/Qualified split only starts working once somebody is
recording outreach again.

**27 records have no stage at all** — all fulfillment. `04` and `05` both leave them alone
deliberately, and `05` does not count them as failures. (This read 28 including 1 buy until that
buy record was given a stage by hand on 2026-08-09.)

## 6a. `clienttype-sync` is running while you do this

Confirmed live on 2026-08-09: `clienttype-sync.timer` fires **every 2 minutes**. §9 notes that it
creates records at the **old** stage names, and it is doing so from a live timer, not one day in
the future. It is currently idle — every run for 24h reported `create=0 tag=0 move=0 flag=3` — but
idle is not stopped, and it writes the moment anyone tags a company.

Two different consequences, only one of which matters:

- a record created **after `04`** makes `05` fail. Harmless: re-run `04`, then `05`.
- a record created **between `05` passing and `06` running** loses its stage when `06` strips the
  option it points at. `05`'s PASS is a snapshot, not a lock, and this is the only route to
  unrecoverable loss left in the migration.

So **stop the timer across the `05` → `06` window** and start it again afterwards:

```sh
sudo systemctl stop  clienttype-sync.timer
python3 05_verify.py            # must PASS
python3 06_remove_old.py --apply
sudo systemctl start clienttype-sync.timer
```

Note the ordering trap: `clienttype-sync` will still be creating records at old stage names when
you start it again, and after `06` those options no longer exist. Restarting it does not restore
correctness — it restores the sync, broken, until it is updated. That is the §9 job.

## 7. Phase 2 — designed, **not scripted**

**No script in this folder touches an existing field.** Everything here is additive, plus the
record re-stage and the old-option removal. These four remain, and an agent must not assume they
have run:

| Change | Why it matters |
|---|---|
| Fulfillment `engagementStatus` → `progressType` | The naming trap: the field labelled *Progress Type* is not called that, so anything written against the obvious name silently goes nowhere |
| `actionItem` relabel → "Next action" | Cosmetic; it is already the plan field |
| `mandate` TEXT → RELATION | Until then no view can list open fulfillments whose mandate has closed — the one item with a real counterparty waiting |
| Retire `lastContacted`, `nextReachOutAt`, `followUpDate`, Sell `engagementStatus` | Superseded by `lastContactedAt` and `nextActionDue`. **Sell's is gated on §4** |

## 8. Rollback

`01`–`04` write a manifest to `manifests/` **before** their first mutation.

This was not true of `02` and `03` until 2026-08-09 — both wrote theirs *after* the mutation loop,
so the sell failure in §5.4 changed two boards and left no rollback record at all. Both now do a
full read pass over every board, write the manifest, and only then mutate. If you are adding a
seventh script, copy that shape: a manifest that only appears once every board succeeded is not a
manifest. The missing one was reconstructed — `02_stage_options-*-backfill.json`, live options minus
the ids beginning `40404040-0000-4000-8000-b`, cross-checked against the counts the pre-apply dry
run printed (8 on buy, 7 on other).

```sh
python3 rollback.py manifests/04_map_stages-<stamp>.json --apply
```

Restores stage options, verdict options and every record's previous stage. It **cannot** undo
`06` — the options are gone and the records that pointed at them were re-staged before it ran.
Fields created by `01` are listed but not deleted, because dropping a field drops its data; that
is left as a deliberate manual step.

## 9. Out of scope — this is preparation, not connection

None of the following is done, and none of it is in this folder:

- ~~**`clienttype-sync` still creates records at the OLD stage names.**~~ **Done 2026-08-09.** Its
  `SEG` map now creates at `LEAD` / `TARGET` / `LEAD` / `APPROACH`; `NETWORK` stays on `REACHED_OUT`
  because `networking` was out of v2's scope and still carries it. Edit the canonical copy at
  `../.crm-automations/clienttype-sync/sync.py`, then `scp` it to `/opt/heydeal-clienttype-sync/`
  (VM backup: `sync.py.bak-pre-v2-20260809`). **Verify by creating a record, not by reading the
  log** — the log says `create=0 errors=0` whether the create path works or not, because it only
  creates when somebody tags a company. There is nothing that checks these five values still match
  the spec's first stages.
- No saved views exist for any of the new fields.
- Nothing writes `Next Owner` or `Next Action Due` automatically — the loops in `WORKFLOWS.md`
  are worked by hand, exactly as they are today.
- No automation, no scheduled job, no engine. `PIPELINE_ENGINES_ENABLED` is still a tombstone.

## 10. Where everything lives

| | |
|---|---|
| The spec everything derives from | `.crm-automations/dashboard/workflow_spec.py` |
| The workflow, written out | `CRM/WORKFLOWS.md` (generated) |
| What is live in the CRM **today** | `CRM/_archive/WORKFLOWS-pre-v2.md` |
| The team-facing version of this | `CRM/MIGRATION.md` |
| Proof nothing has been applied | `python3 _snapshot.py` |
