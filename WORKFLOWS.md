# Nobridge pipeline workflows — the operating manual

> **What this is.** One written model for how a deal moves through Nobridge, bound to the exact
> fields on the exact CRM boards. Every step below names the CRM state that triggers it and the CRM
> writes it produces, so "where is this deal" has one answer no matter who you ask.
>
> **Why it exists.** Until August 2026 there were two systems. A rules engine kept its own state
> machine in a private database — sub-states like `NEW_LEAD:AWAITING_OUTREACH` and `DORMANT:HELD_OFF`
> — and fired tasks off it. Meanwhile people filled in `Stage`, `Progress Type` and `Final Decision`
> in the CRM by hand, with no defined relationship between them. Neither knew what the other meant.
> The engine was switched off on 2026-08-07 (§10). This document is the merge: the engine's rules,
> re-expressed entirely in fields that are visible on the record.
>
> **Status of the automation.** Only **Call Intelligence** runs today (§8). Everything else here is
> done by hand. The rules are still the rules — a human following them and a machine enforcing them
> should produce the same record.
>
> **Prefer a picture?** All three pipelines are drawn as flowcharts on the ops dashboard, at two
> altitudes. **node.nobridge.co → High Level Workflows** is the shape of a pipeline on one screen,
> with the step list behind **Show details**. **→ Workflow** is the same rules with nothing
> collapsed: every send, every timer, every reply check and every field write as its own node —
> where the summary draws one box for a chase ladder, that one draws *wait 4 days → send chase 2
> of 4 → replied?*. Source: `.crm-automations/dashboard/workflow_charts.py`, `workflow_detail.py`
> and `dashboard.py` (`CATALOG`). All of them are hand-maintained renderings of §3–5 below —
> this document is the original, and nothing checks that the copies still agree with it.

---

## 1. How to read a deal — the four axes

A deal's status is not one field. It is four independent questions, and each has exactly one field
that answers it. Most of the confusion in the CRM today comes from answering one question with
another field's value.

| Axis | The question | Field | Set by | Rolls back? |
|---|---|---|---|---|
| **Position** | How far did this conversation get? | `stage` | Evidence of a step actually taken | **Never.** It freezes at the furthest point reached |
| **Pulse** | Is it alive *right now*? | `progressType` | The clock — did they reply, or has it gone quiet | Constantly |
| **Meeting** | What happened to the booked meeting? | `meetingOutcome` | Calendar sync, then the call note | Per meeting |
| **Verdict** | Is it over, and how? | `finalDecision` · `outcome` on Fulfillment | A person, once, at the end | No — terminal |

And underneath them, **the clock** — the timestamps that make Pulse derivable instead of guessed:
`outreachSentAt` · `repliedAt` · `strategySentAt` · `revampSentAt` · `recapSentAt` ·
`escalatedAt` · `nextReachOutAt` (Sell) · `followUpDate` + `lastContact` (Fulfillment).

### The three rules that follow from this

**Position never reverses.** A deal that reached Stage 6 and then died stays at Stage 6. The board
is a record of how far you got, not a to-do list. This is already how the data is filled in — 32 of
the 35 sell deals sit at Stage 6 while being closed — so this rule makes the existing convention
official rather than moving anything.

**Pulse is derived, not typed.** It answers only "is this conversation warm":

| Value | Means | Condition |
|---|---|---|
| `Actively Speaking / In Chase` | Live | Outreach sent **and** (they replied within 14 days **or** a future reach-out is scheduled) |
| `Ghosted` | Gone quiet | 14 calendar days of silence after the last outbound touch, chase ladder exhausted |
| `Complete` | Done with | A verdict is set |

**Blank verdict means open.** `finalDecision` stays empty for the entire life of a live deal. It is
filled in once, at the end. `No Decision Made` is *not* "we haven't decided yet" — it means the deal
ran its course and the other side never came back with an answer. That is terminal.

> **Known backlog.** 40 of 99 buy deals currently carry `No Decision Made` while sitting in Stage 1
> or Stage 2 — using the verdict field as a live status. Those need reconciling to blank, or to a
> real verdict. Tracked as the Phase 4 backfill; not corrected by this document.

---

## 2. The field dictionary

Five boards. A Company's `Client Type` tag decides which ones it appears on, and
`.crm-automations/clienttype-sync` creates the record within ~2 minutes of tagging.

| `Company.clientType` | Board | API object | Record count (2026-08-08) | Created at stage |
|---|---|---|---|---|
| `Buy side` | Buy Side Opportunities | `buyOpportunity` | 99 | `Stage 1 · New Lead` |
| `Sell side` | Sell Side Opportunities | `sellOpportunity` | 35 | `Stage 1 · New Lead` |
| `Other opportunities` | Other Opportunities | `otherOpportunity` | 5 | `Stage 1 · New Lead` |
| `Fulfillment` | Fulfillments | `fulfillment` | 348 | `Reached Out / Teaser` |
| `Network` | Network | `networking` | 75 | `Reached Out` |

`Client Type` is a MULTI_SELECT — a company can be on several boards at once. Untagging does **not**
delete the deal; it only stops the sync from maintaining it.

### 2.1 The opportunity boards — Buy, Sell, Other

These three were cloned from one object and have since drifted apart. The differences are real and
matter, so they are listed rather than smoothed over.

**`stage`** — Position. Identical first six on all three boards:

| Value | Label |
|---|---|
| `NEW_LEAD` | `Stage 1 · New Lead` |
| `MEETING_1` | `Stage 2 · Intro Meeting + Screening` |
| `STRATEGY` | `Stage 3 · Strategy / Value Creation` |
| `MEETING_2` | `Stage 4 · Strategy Review` |
| `REVAMPS` | `Stage 5 · Revamps` |
| `MEETING_3` | `Stage 6 · Service Evaluation + Pitch` |

Then they diverge — **Buy** ends `Completed` / `Skipped`; **Sell** and **Other** end `Closed Won`
with no equivalent of `Skipped`. There is no `Lost` and no `Dormant` stage on any board, and there
should not be: both are verdict/pulse states, not positions (§7).

**`progressType`** — Pulse. Same on all three: `Actively Speaking / In Chase` · `Ghosted` ·
`Complete`.

**`meetingOutcome`** — Meeting. Same on all three: `Scheduled` · `Hosted` · `No-show` ·
`Rescheduled` · `Cancelled`.

**`finalDecision`** — Verdict. **Buy has seven options; Sell and Other have three.**

| Option | Buy | Sell | Other |
|---|:-:|:-:|:-:|
| `Closed Won` | ✓ | ✓ | ✓ |
| `Closed Lost` | ✓ | ✓ | ✓ |
| `No Decision Made` | ✓ | ✓ | ✓ |
| `Not Interested` | ✓ | — | — |
| `Disqualified` | ✓ | — | — |
| `Follow Up (90)` | ✓ | — | — |
| `Follow Up (180)` | ✓ | — | — |

`Follow Up (90)` and `Follow Up (180)` are the closed loop written down (§9): closed for now, come
back in 90 or 180 days.

**`engagementStatus`** — **Sell only.** `In Discussions / Scheduled` · `Awaiting Reply` ·
`Held Off` · `Crash Out / DNC`. This is a second, overlapping pulse axis that Buy and Other do not
have, and it is the field the retired sell cadence wrote into. Under the model above it is
redundant: `Held Off` is `Ghosted` + a future reach-out date, and `Crash Out / DNC` is a verdict.
Only 3 of 35 sell deals use it. Retiring it is Phase 2 work; until then, `progressType` is
authoritative and `engagementStatus` is legacy.

**The clock and the rest:**

| Field | Type | Label | On |
|---|---|---|---|
| `outreachSentAt` | DATE_TIME | Outreach Sent At | all three |
| `repliedAt` | DATE_TIME | Replied At | all three |
| `strategySentAt` | DATE_TIME | Strategy Sent At | all three |
| `revampSentAt` | DATE_TIME | Revamp Sent At | all three |
| `recapSentAt` | DATE_TIME | Recap Sent At | all three |
| `escalatedAt` | DATE_TIME | Escalated At | all three |
| `nextReachOutAt` | DATE_TIME | Next Reach-Out At | **Sell only** |
| `closeDate` | DATE_TIME | Close date | all three |
| `amount` | CURRENCY | Amount | all three |
| `revampNeeded` | BOOLEAN | Revamp Needed | all three |
| `nextSteps` | TEXT | **Where we last left off** | all three |
| `actionItem` | TEXT | Action Item | all three |
| `reasonForProgress` | TEXT | Reason for progress | all three |
| `lastContacted` | **TEXT** | Last Contacted | all three |

> **Two traps in that table.**
> `lastContacted` is **text**, not a date — it holds phrases like `4 days ago` and
> `No contact logged`, rewritten nightly at 06:30. You cannot filter or sort a pipeline on it, and a
> value read at any other moment is stale. Treat it as a glance, never as data.
> `nextSteps` is labelled **"Where we last left off"** in the UI — it is a *history* note, not a
> plan. The plan goes in `actionItem`.

> **The clock is currently empty.** All six timestamp fields read 0 of 99 on the buy board: their
> values were the retired engine's and were cleared on 2026-08-07. The fields still exist. Until
> they are being written again, Pulse cannot be derived and has to be judged by eye.

### 2.2 Fulfillment

A different process — running a sell-side mandate against a list of approach targets — so a
different ladder.

**`stage`** — `Reached Out / Teaser` → `Meeting 1` → `NDA` → `Meeting 2` → `Due Diligence` →
`Meeting 3` → `Waiting on Offer`.

**`engagementStatus`** — Pulse. `Complete` · `Actively Speaking` · `Ghosted`.

> **The naming trap.** In the CRM this field is **labelled "Progress Type"**, but its API name is
> `engagementStatus` — *not* `progressType`, which is what the opportunity boards use. The options
> match `progressType` but are listed in a different order. Anything written against
> `fulfillment.progressType` silently goes nowhere. Renaming it is Phase 2 work.

**`outcome`** — Verdict. `Offer Received` · `Passed` · `Dropped`.

**`prospectType`** — segmentation, not status: `Level 1 : Competitor / Direct Relation` ·
`Level 2 : Supporting Business` · `Level 3 : Expansion` · `PE / VC`.

**Better instrumented than the opportunity boards** — these are real dates, refreshed nightly at
06:35: `lastContact` (DATE) · `daysSinceContact` (NUMBER, = today − lastContact) ·
`followUpDate` (DATE — Fulfillment's name for `nextReachOutAt`). Also `mandate` (which client this
approach is for), `meetingFindings`, `fathomLink`, `secondaryContacts`, `notes`, `nextSteps`,
`companyType`, `country`, plus `repliedAt` and `escalatedAt`.

### 2.3 Network

Investor relationship tracking. **Out of scope for this manual** — it has no chase ladder and never
had an engine. Recorded here so its fields are not mistaken for the others':

`stage` — `Reached Out` · `Intro Call` · `Ongoing Dialogue` · `Actively Engaged`.
`engagementStatus` — its own six-option set: `Not Contacted Yet` · `In Discussions / Scheduled` ·
`Awaiting Reply` · `Held Off (Check Back In 3 Months)` · `Not Interested` · `Crash Out (DNC)`.
Plus `investorType`, `country`, `nextSteps`, `lastContact`, `followUpDate`.

All 75 records sit at `Reached Out` — the stage has never been advanced on this board.

---

## 3. Buy-side

Deals where Nobridge helps someone buy a business.

### 3.1 The spine — promotions

This is what the old engine never modelled and what nobody wrote down: **when a deal earns its next
stage.** Each row is a step; the trigger is the real-world event, and the writes are what the record
must look like afterwards.

| ID | Step | Trigger — the actual event | CRM writes |
|---|---|---|---|
| — | Deal appears | Company tagged `Buy side`; sync creates it within ~2 min | `stage = Stage 1 · New Lead` |
| **A01** | Answer the lead | Intro + booking link goes out. **24 h** from the lead landing | `outreachSentAt = now` · `progressType = Actively Speaking` |
| **P01** | → **Stage 2 · Intro Meeting + Screening** | A meeting is **booked** — *not held* | `stage = Stage 2` · `meetingOutcome = Scheduled` |
| **A02** | Confirmation + agenda | Meeting booked. **24 h** | *(nothing stamped — see the gap below)* |
| **X01** | Record the call | Gemini notes for that meeting are ingested | `meetingOutcome = Hosted` · note filed on Company + Contact + deal · action items queued for approval |
| **A03** | Send the recap | Meeting hosted. **24 h** | `recapSentAt = now` |
| **P02** | → **Stage 3 · Strategy / Value Creation** | We commit to producing the strategy document | `stage = Stage 3` — starts the 10-day A04 clock |
| **A04** | Deliver the strategy document | **10 days** from entering Stage 3 | `strategySentAt = now` |
| **P03** | → **Stage 4 · Strategy Review** | The review meeting is **booked** | `stage = Stage 4` · `meetingOutcome = Scheduled` |
| **P04** | → **Stage 5 · Revamps** | Revamps are agreed on the review call | `stage = Stage 5` · `revampNeeded = true` |
| **A05** | Deliver the revamps | **7 days** from entering Stage 5 | `revampSentAt = now` |
| **P05** | → **Stage 6 · Service Evaluation + Pitch** | The pitch meeting is **booked** | `stage = Stage 6` · `meetingOutcome = Scheduled` |
| **P06** | Close it out | A decision is reached | `stage = Completed` · `finalDecision = <verdict>` · `closeDate = now` · `progressType = Complete` |
| **P07** | Disqualify | Never a real process — wrong fit, no mandate, no interest | `stage = Skipped` · `finalDecision = Disqualified` or `Not Interested` · `progressType = Complete` |

> **The distinction to hold on to.** A meeting being **booked** promotes the stage. The **call note**
> records what happened to it (`meetingOutcome = Hosted`). Two different events, at two different
> moments, writing two different fields. Collapsing them into one manual stage drag — which is what
> happens today — is why the board and the calendar disagree.

**Stages 4 and 6 repeat the Stage 2 pattern exactly**: confirmation and agenda before, call note and
recap after, no-show recovery if it is missed.

**A gap worth knowing:** A02 (confirmation + agenda) stamps nothing. There is no field that records
whether the agenda went out, so after the fact it is unrecoverable from the CRM. Same for D04.

### 3.2 The chases — when they go quiet

Each ladder runs from the last outbound touch, one open chase at a time. Day offsets are cumulative
and calendar-based; every touch lands inside business hours, **09:00–18:00 Asia/Jakarta, Mon–Fri**.

| ID | Chase | Runs when | Ladder |
|---|---|---|---|
| **B01** | Chase for a booking | `Stage 1` · `outreachSentAt` set · no meeting booked | days **2 · 6 · 14 · 30** → then dormant → C01 |
| **B02** | Recover the no-show | `meetingOutcome = No-show` | reschedule now, then the same 2 · 6 · 14 · 30 |
| **B03** | Chase to book Stage 4 | `Stage 3` · `strategySentAt` set · no next meeting | days **2 · 6 · 12 · 20** |
| **B04** | Chase to book Stage 6 | `Stage 5` · `revampSentAt` set · no next meeting | days **2 · 6 · 12 · 20** |
| **C01** | Re-engage | Dormant — ladder exhausted | one fresh touch at **+90 days**, one bump at **+97** |
| **D04** | Re-confirm | `meetingOutcome = Rescheduled` or `Cancelled` | re-confirm within **24 h** |

**When a ladder exhausts:** `progressType = Ghosted`, and the next re-engage date is recorded. The
deal is not closed — it is parked, and C01 picks it back up.

> The **Workflow** tab draws every one of these touches individually — the wait, the send and the
> "did they reply" check between each pair — and it derives them from this table. Change a day
> offset here and `workflow_detail.py` is wrong until someone changes it too.

### 3.3 Interrupts

| ID | Interrupt | Trigger | Effect |
|---|---|---|---|
| **D01** | They reply | An inbound email from the point of contact | Every chase stops. `repliedAt = now` · `progressType = Actively Speaking`. One thing to do: read it and answer |
| **D02** | Lost | `finalDecision` set to a losing verdict | Everything open closes out |
| **D03** | Won | `finalDecision = Closed Won` | Everything open closes out |

A reply always beats a chase. Nothing scheduled survives it.

---

## 4. Sell-side

Outbound to potential sellers. One fixed cadence that stops the moment someone answers.

The **same six stages** as Buy, and the same promotion rules (§3.1) — a booked meeting promotes, a
call note records. Where Sell differs: the entry is a cold ladder rather than an inbound lead, and
the board terminates at `Closed Won` rather than `Completed` / `Skipped`.

### 4.1 The cadence

Each step fires only if there has been no reply since the previous touch. Business hours here are
**08:00–17:00 Asia/Jakarta**.

| # | Step | Delay from the previous touch | What it means about the deal |
|---|---|---|---|
| **S01** | First reach-out | — | `outreachSentAt = now` · `progressType = Actively Speaking` |
| 1 | 2nd reach-out | **+2 business days** | — |
| 2 | 3rd reach-out | **+5 business days** | — |
| 3 | Ghosted — re-engage | **+14 calendar days** | `progressType = Ghosted` |
| 4 | Re-engage follow-up | **+5 business days** | — |
| 5 | 3-month re-engage | **+90 calendar days** | parked — `nextReachOutAt` carries the date |
| 6 | 3-month re-engage, 2nd try | **+3 business days** | — |
| — | Ladder exhausted | — | Do not contact. Verdict, not pulse — see below |

Every step writes `nextReachOutAt` = the next touch's date. That field is the only forward-looking
one on the board and is what makes "waiting on them" a filterable state rather than a feeling.

> This table is what the **Workflow** tab draws touch by touch, one wait node and one reply check
> per row above. Edit the delays here and `workflow_detail.py`'s `SELL_CADENCE` needs the same edit.

> **Those marks are gone.** The cadence used to write `Ghosted` onto 16 deals and `Held Off` onto 5
> — machine output that read like someone's judgement. All of them were cleared in the 2026-08-07
> field-footprint pass (§10), so today the sell board's pulse is `Complete` on 15, `Actively
> Speaking` on 4, and **blank on 16**. Anything you see there now was typed by a person.

### 4.2 Interrupts

| ID | Interrupt | Effect |
|---|---|---|
| **SD01** | They reply | Cadence stops. `repliedAt = now` · `progressType = Actively Speaking`. One thing to do: meet them to understand what they need |
| **ST01** | Closed | Won, lost or do-not-contact → everything open closes out |

---

## 5. Fulfillment

Approaching targets on behalf of a live sell-side mandate. `mandate` says which client.

### 5.1 The spine

| ID | Step | Trigger | CRM writes |
|---|---|---|---|
| — | Record appears | Company tagged `Fulfillment`, or a mandate list import | `stage = Reached Out / Teaser` |
| **FP01** | → **Meeting 1** | Intro meeting booked | `stage = Meeting 1` |
| **X01** | Record the call | Gemini notes ingested | note filed · `meetingFindings` updated · action items queued |
| **FP02** | → **NDA** | NDA sent for signature | `stage = NDA` |
| **FP03** | → **Meeting 2** | Second meeting booked | `stage = Meeting 2` |
| **FP04** | → **Due Diligence** | VDR opened to them | `stage = Due Diligence` |
| **FP05** | → **Meeting 3** | Third meeting booked | `stage = Meeting 3` |
| **FP06** | → **Waiting on Offer** | They confirm an offer is being prepared | `stage = Waiting on Offer` |
| **FP07** | Close it out | Offer lands, they pass, or they go dark for good | `outcome = Offer Received \| Passed \| Dropped` · `progressType = Complete` |

Unlike Buy and Sell there is no `Skipped` — a target that never engages is `Dropped`.

### 5.2 The chase

One ladder, cumulative days **2 · 4 · 8 · 12 · 26** from the last touch, business hours
**09:00–17:00 Asia/Jakarta**. Two variants, same timing, different tone:

| ID | Variant | Runs when |
|---|---|---|
| **F01** | Chase for a response | Pulse is `Ghosted` or blank — they have not engaged |
| **F02** | Nudge it along | Pulse is `Actively Speaking` — keep the process moving |

Runs **at most twice**: the initial cycle, then — if still silent — a **+14-day** re-engagement that
repeats the same ladder once. After the second cycle, chasing stops and the record is handed back
for a human decision. `followUpDate` carries the next touch; `daysSinceContact` shows the drift.

> The **Workflow** tab draws both cycles in full, five touches each, from these offsets — and
> draws §5.1's seven stages as seven nodes rather than the single box the summary chart uses.

### 5.3 Interrupts

| ID | Interrupt | Effect |
|---|---|---|
| **FD01** | They reply | All chases stop. `repliedAt = now` · `progressType = Actively Speaking` |
| **FT01** | Completed | `outcome` recorded, or pulse set to `Complete` → everything open closes out |

**No 90-day loop here, deliberately.** A fulfillment record is an approach target for a specific
mandate. When the mandate ends the target is not re-approached on its own — it becomes a Buy-side
lead if it is worth one.

---

## 6. Play ↔ CRM binding

The merge, in one table. The left column is the retired engine's internal state; the middle is the
same thing expressed in fields that are visible on the record. **Nothing on the left needs to exist
any more** — that is the point.

| Engine sub-state | The same thing, in CRM fields | Play |
|---|---|---|
| `NEW_LEAD : AWAITING_OUTREACH` | `Stage 1` ∧ `outreachSentAt` empty | A01 |
| `NEW_LEAD : AWAITING_BOOKING` | `Stage 1` ∧ `outreachSentAt` set | B01 |
| `MEETING_1/2/3 : SCHEDULED` | `Stage 2/4/6` ∧ `meetingOutcome = Scheduled` | A02 |
| `MEETING_1/2/3 : HOSTED` | `Stage 2/4/6` ∧ `meetingOutcome = Hosted` | A03 |
| `MEETING_1/2/3 : NO_SHOW` | `meetingOutcome = No-show` | B02 |
| `MEETING_1/2/3 : RESCHEDULED` | `meetingOutcome ∈ {Rescheduled, Cancelled}` | D04 |
| `STRATEGY : AWAITING_DOC` | `Stage 3` ∧ `strategySentAt` empty | A04 |
| `STRATEGY : AWAITING_BOOKING` | `Stage 3` ∧ `strategySentAt` set | B03 |
| `REVAMPS : AWAITING_REVAMP` | `Stage 5` ∧ `revampSentAt` empty | A05 |
| `REVAMPS : AWAITING_BOOKING` | `Stage 5` ∧ `revampSentAt` set | B04 |
| **`DORMANT : HELD_OFF`** | `progressType = Ghosted` ∧ a re-engage date is set | C01 |
| **`LOST : TERMINAL`** | `finalDecision ∈ {Closed Lost, Not Interested, Disqualified}` | D02 |
| `CLOSED_WON : TERMINAL` | `finalDecision = Closed Won` | D03 |
| `NEW : AWAITING_OUTREACH` (sell) | `outreachSentAt` empty ∧ never replied | S01 |
| `ACTIVE : CHASE` (sell) | `outreachSentAt` set ∧ `repliedAt` empty | S02 |
| `ACTIVE : CHASE` (fulfillment) | pulse `Ghosted` or blank | F01 |
| `ACTIVE : ENGAGED` (fulfillment) | pulse `Actively Speaking` | F02 |
| `TERMINAL : DONE` (fulfillment) | `outcome` set, or pulse `Complete` | FT01 |

**`DORMANT` and `LOST` are not stages** and must never be added as ones. Dormant is a pulse value
plus a future date; Lost is a verdict. The stage column stays a record of how far the conversation
got.

### The eight status buckets

The engine sorted every record into one of eight buckets. They remain a good vocabulary for reading
a board by eye, and each is now a filter you could actually build:

| Bucket | Reads as | Filter |
|---|---|---|
| Needs response | The ball is in our court | `repliedAt` newer than our last touch |
| Meeting booked | Send confirmation + agenda | `meetingOutcome = Scheduled` |
| On task | We owe a deliverable | in a deliverable stage with its `*SentAt` empty |
| Follow-up due | A chase touch is owed | next reach-out date is today or past |
| Waiting on them | Nothing to do right now | next reach-out date is in the future |
| Dormant | Parked, will come back | `progressType = Ghosted` + a re-engage date |
| No automation | Human-managed | none of the above |
| Closed | Over | `finalDecision` / `outcome` set |

---

## 7. What runs today, and what is proposed

### Running now

**Call Intelligence** — the only pipeline automation still live. Every 15 minutes it reads the
Gemini notes from ended Google Meet calls, files **one note on the Company, the Contact and the
deal**, and extracts the follow-ups. Those follow-ups are **not** written straight in: they queue on
**node.nobridge.co → Calls** and become real CRM tasks only when a person approves them.

**Client Type sync** — every 2 minutes; tags on a Company create and maintain its deals across the
five boards.

**Nightly refreshes** — `lastContacted` phrases at 06:30; Fulfillment's `lastContact` and
`daysSinceContact` at 06:35.

### Proposed, in the order it should be built

**Tier 1 — keep state, create no tasks.** The CRM stamps its own clock (`stageChangedAt` on every
stage move, `lastContactedAt` from message sync) and derives `progressType` from it. Overdue work
appears as saved views on the board, never as a generated task. Zero noise by construction. Twenty
v2.7.3 can do all of this natively — cron and database-event triggers, find/filter/iterate/update
actions — with no external service.

**Tier 2 — call notes drive the moves.** Extend Call Intelligence to set `meetingOutcome = Hosted`
and to *propose* the stage promotion and the verdict, queued on the Calls tab alongside the action
items it already queues. This is the only automation with any understanding of what was said, which
is precisely what the retired engines lacked.

**Tier 3 — the chase ladders.** §3.2, §4.1 and §5.2 rebuilt as native CRM workflows that create real
tasks. **Built last and behind a switch.** This is the tier that produced 440 tasks nobody wanted;
Tiers 1 and 2 have to be trusted first.

None of this needs the old engine. `PIPELINE_ENGINES_ENABLED` stays a tombstone (§10).

---

## 8. The closed loop

The pipeline is meant to be **closed**. A deal that dies is not dropped — it goes back to the
original contact for a fresh check-in after about **90 days**, and if they bite it rejoins the normal
chase as a live deal.

| Pipeline | Closed loop? | Where it rejoins | How it is recorded |
|---|---|---|---|
| Buy-side | Yes | Lost → 90 days → re-engage → back onto the B01 ladder | `finalDecision = Follow Up (90)` or `(180)` |
| Sell-side | Yes | Do-not-contact → 90 days → re-engage → back onto the cadence | *(no field for it yet — Phase 2)* |
| Fulfillment | **No, deliberately** | — | Mandate work, not a prospect to re-approach |

**The engine never did this.** On buy-side it cancelled everything at Lost and stopped; on sell-side
it marked do-not-contact and stopped. The 90-day re-engage that did run only ever fired for a lead
that *went quiet*, never for one marked Lost. On the dashboard's flowcharts this loop is drawn in
**violet and dashed** so it is never confused with what actually ran.

Buy-side is the only board that can currently express it, via `Follow Up (90)` / `Follow Up (180)`.
Two deals carry each today.

---

## 9. Business hours

| | Buy | Sell | Fulfillment |
|---|---|---|---|
| Hours | 09:00–18:00 | 08:00–17:00 | 09:00–17:00 |

Timezone `Asia/Jakarta`, business days Monday–Friday, on all three. Offsets marked **BD** are
business days; plain day counts are calendar days. Every scheduled touch snaps forward into the next
open window, so nothing is timed for 02:00 on a Sunday.

---

## 10. History — the retired rules engine

**Retired 2026-08-07.** The buy-side, sell-side and fulfillment rules engines are off for good, and
the rules above are now followed by hand. Do not resurrect them without being asked.

**Why.** The engine matched on stage and timestamps only. It had no idea what was actually said in a
conversation, so its tasks were noise. It created **440 tasks** in the CRM, all deleted on
retirement, along with the **150 field values** it had written itself — `escalatedAt`, `repliedAt`,
the `*SentAt` stamps, `nextReachOutAt`, and the 16 `Ghosted` / 5 `Held Off` marks the sell cadence
applied. `meetingOutcome` was kept, because it derives from real calendar events. Per-record prior
values are in `_backups/20260807-preremoval/engine_field_footprints.tsv`.

**What it was.** A Node service reconciling every 5 minutes off the CRM and ticking every 60 seconds,
holding lead state, a job queue and a task ledger in its own SQLite database. Twenty's SSRF
protection blocked its webhooks, so the poll was the only live path. Three parallel engines, one per
board, routed by the automation-id prefix (`S*` sell, `F*` fulfillment, everything else buy).

**Things it did that are easy to forget:**

- A01/A02/A03 and the chases auto-completed when an outbound email to the contact was detected.
  **A04 and A05 never did** — a sent email is not proof a document went out, so they were closed by
  hand. That judgement still holds.
- Missing an SLA stamped `escalatedAt` on the deal. That stamp *was* the escalation — the Google
  Chat notification layer it used to ping had been deleted the day before, on 2026-08-06.
- Calendar sync auto-wrote `meetingOutcome` (`Scheduled` / `Hosted`) when the contact's email
  appeared in a synced calendar event, respecting any manual value other than `Scheduled`.

**Task titles it produced** — useful only for recognising a leftover. Bodies carried a one-line
`Buy-side:` / `Sell-side:` / `Fulfillment:` prefix, which is what distinguished them from Call
Intelligence tasks.

*Buy* — `Respond to new lead: {n} (intro + booking link)` · `Send confirmation + agenda: {n} (Mtg {k})` ·
`Send recap / summary: {n} (Mtg {k})` · `Produce + send strategy doc: {n}` · `Deliver revamps: {n}` ·
`Follow up, no booking yet: {n} (touch {i})` · `Reschedule no-show: {n} (Mtg {k})` ·
`Follow up to rebook: {n} (touch {i})` · `Follow up to book Mtg 2: {n} (touch {i})` ·
`Follow up to book Mtg 3: {n} (touch {i})` · `Re-engage, new thread: {n}` · `Re-engage bump: {n}` ·
`Re-confirm rescheduled meeting: {n} (Mtg {k})` · `Reply in — review & respond: {n}`

*Sell* — `Reach out to {n} (1st)` · `2nd reach-out: {n}` · `3rd reach-out: {n}` ·
`Ghosted — re-engage (2 weeks): {n}` · `Re-engage follow-up: {n}` · `3-month re-engage: {n}` ·
`3-month re-engage (2nd): {n}` · `Reply in — meet to understand needs: {n}`

*Fulfillment* — `Follow up (no response): {n} (touch {i})` · `Keep {n} moving to the next step (touch {i})` ·
`Re-engage: {n} (touch {i})` · `Reply in — review & respond: {n}`

**Where the dormant source lives** — `Desktop/Nobridge Software/Sales Engine VM`. Buy plays
`src/automations/registry.ts` · buy ladders `patterns.ts` · sell cadence `sellPatterns.ts` ·
fulfillment ladder `fulfillmentPatterns.ts` · stage tables `src/core/stateMachine.ts` and its sell
and fulfillment siblings · completion stamps `src/core/taskManager.ts` · business hours
`src/config.ts`. That container now runs **Call Intelligence only**.

Historical engine state — lead states, job queue, task ledger, bucket history — was exported to JSON
before the wipe and lives with the retirement backups, **outside this repo**, since it contains
contact names and email addresses.
