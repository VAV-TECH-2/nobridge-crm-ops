# Nobridge pipeline workflows — the operating manual

> **GENERATED FILE — do not edit.** Written by `.crm-automations/dashboard/workflow_doc.py` from `workflow_spec.py`:
>
> ```sh
> cd .crm-automations/dashboard && python3 workflow_doc.py > ../../WORKFLOWS.md
> ```
>
> Edit the spec and regenerate. Until 2026-08-09 this document, the two chart tabs and the dashboard's step list were four hand-kept copies of one ruleset, and this file had to warn you twice that nothing checked they agreed. They are now one source.

> ## ⚠ The CRM has not been migrated yet.

> The boards still carry the old six stages. Several stages named below — **Qualified**, **Negotiation**, **Target**, **Engaged**, **Offer Expected** — do not exist on any board today, and the fields marked NEW are not there either. What is actually live is preserved at [`_archive/WORKFLOWS-pre-v2.md`](./_archive/WORKFLOWS-pre-v2.md) and stays true until `.crm-migrate-v2` is applied. Use that file to work a deal today; use this one to understand where the pipeline is going.

> **What is changing, in plain language:** [`MIGRATION.md`](./MIGRATION.md) — which stages move, where every deal lands, and what to do differently. The runbook for whoever applies it is [`.crm-migrate-v2/RUNBOOK.md`](./.crm-migrate-v2/RUNBOOK.md).

Three pipelines redrawn: stages split where one stage was doing two jobs, a Negotiation stage where today there is nothing between the pitch and the close, and every chase written as a named loop with its parameters on the face of it.

---

## 1. Why the stages move

Buy's Stage 1 currently means both “a lead arrived” and “we are chasing a lead”. Those need different work and different reporting, and conflating them is why 40 deals sit there with a verdict typed on them as a status.

Nothing at all sits between Pitch and Closed — no terms, no paperwork, no signature. That is where an advisory deal spends its last six weeks, and the board cannot see any of it.

A chase ladder is currently twelve anonymous nodes. How many touches it has, what ends it, and where the record goes when it runs out are all implicit — which is how five ladders came to simply stop, with nothing catching what fell out.

---

## 2. What changes

| Pipeline | Stages | Steps | New steps | Named loops |
|---|---|---|---|---|
| Buy-side | 8 → 9 | 24 → 48 | 17 | 10 |
| Sell-side | 7 → 10 | 25 → 49 | 20 | 11 |
| Fulfillment | 7 → 9 | 14 → 38 | 14 | 6 |

---

## 3. The loop catalogue

Every chase, re-engagement and SLA as one named object, defined once and used wherever it genuinely is the same loop. **`on exhaust` is the row that does not exist today** — five of the current ladders simply stop, which is where all twenty-four dead ends came from.

### L1 · Booking chase (cold)

| Parameter | Value |
|---|---|
| touches | 4 |
| schedule | day 2 · 6 · 14 · 30 |
| entry | Outreach Sent At set ∧ no meeting booked |
| exit | they reply, or a meeting is booked |
| on reply | owner → Us · due +1 BD |
| on exhaust | → L9 · Ghosted, re-engage date set |
| escalation | none — the loop is the escalation |
| used by | buy · sell |
| today | B01, unchanged |

### L2 · Qualification chase

| Parameter | Value |
|---|---|
| touches | 3 |
| schedule | day 1 · 3 · 7 |
| entry | Stage = Lead ∧ Qualified is empty |
| exit | qualified, or disqualified |
| on reply | owner → Us · due +1 BD |
| on exhaust | → Closed · Disqualified — no answer to a screening question is an answer |
| escalation | day 7 → the owner's manager |
| used by | buy · sell · fulfillment |
| today | NEW — nothing screens a lead today |

### L3 · Go-ahead chase

| Parameter | Value |
|---|---|
| touches | 4 |
| schedule | day 2 · 6 · 12 · 20 |
| entry | Recap Sent At set ∧ the next stage has not been agreed |
| exit | they agree, or they reply |
| on reply | owner → Us · due +1 BD |
| on exhaust | → L9, except after the pitch, where it closes as No Decision Made |
| escalation | none |
| used by | buy · sell · fulfillment |
| today | B05, added 8 Aug |

### L4 · No-show recovery

| Parameter | Value |
|---|---|
| touches | 5 |
| schedule | immediately, then day 2 · 6 · 14 · 30 |
| entry | Meeting Outcome = No-show, Rescheduled or Cancelled |
| exit | the meeting is re-booked |
| on reply | owner → Us · due +1 BD |
| on exhaust | → L9 |
| escalation | none |
| used by | buy · sell · fulfillment |
| today | B02 + D04, merged |

### L5 · Deliverable SLA

| Parameter | Value |
|---|---|
| touches | 2 |
| schedule | at the SLA, then +3 days |
| entry | In a deliverable stage ∧ its Sent At is empty |
| exit | the deliverable goes out |
| on reply | n/a — this one fires on us, not on them |
| on exhaust | → the owner's manager, and the deal stays put |
| escalation | Escalated At = now on the first touch |
| used by | buy · sell |
| today | NEW — nothing watches our own deadlines |

### L6 · Booking chase (warm)

| Parameter | Value |
|---|---|
| touches | 4 |
| schedule | day 2 · 6 · 12 · 20 |
| entry | A deliverable has gone out ∧ no next meeting is booked |
| exit | a meeting is booked |
| on reply | owner → Us · due +1 BD |
| on exhaust | → L9 |
| escalation | none |
| used by | buy · sell |
| today | B03 + B04 — one loop, drawn twice |

### L7 · Negotiation chase

| Parameter | Value |
|---|---|
| touches | 4 |
| schedule | day 3 · 7 · 14 · 21 |
| entry | Stage = Negotiation ∧ no response since the last send |
| exit | terms agreed, or a decision |
| on reply | owner → Us · due +1 BD |
| on exhaust | → Closed · No Decision Made |
| escalation | day 14 → the owner's manager |
| used by | buy · sell |
| today | NEW — there is no Negotiation stage today |

### L8 · Signature chase

| Parameter | Value |
|---|---|
| touches | 4 |
| schedule | day 2 · 5 · 10 · 20 |
| entry | A document is out for signature ∧ unsigned |
| exit | signed |
| on reply | owner → Us · due +1 BD |
| on exhaust | → L9 |
| escalation | day 10 → the owner's manager |
| used by | buy · sell · fulfillment |
| today | NEW — an unsigned NDA is invisible today |

### L9 · Dormant re-engage

| Parameter | Value |
|---|---|
| touches | 2 |
| schedule | +90 days, bump at +97 |
| entry | Ghosted ∧ the re-engage date has arrived |
| exit | they reply |
| on reply | back to the stage it stalled at · owner → Us · due +1 BD |
| on exhaust | → a verdict. Dormant is not a resting place |
| escalation | none |
| used by | buy · sell |
| today | C01 — exists, but only one of five ladders feeds it |

### L10 · Closed loop

| Parameter | Value |
|---|---|
| touches | 2 |
| schedule | +90 days, then +180 |
| entry | Final Decision = Follow Up (90) or Follow Up (180) |
| exit | they reply → the deal rejoins L1 as a live lead |
| on reply | new deal at Stage 2 · owner → Us · due +1 BD |
| on exhaust | → terminal. Genuinely finished |
| escalation | none |
| used by | buy · sell |
| today | Designed, never built (WORKFLOWS.md §8) |

### L11 · Cold cadence

| Parameter | Value |
|---|---|
| touches | 6 |
| schedule | +2 BD · +5 BD · +14 d · +5 BD · +90 d · +3 BD |
| entry | Stage = Contacted ∧ Replied At is empty |
| exit | they reply |
| on reply | → Stage Engaged · owner → Us · due +1 BD |
| on exhaust | → Closed · No Decision Made. NOT do-not-contact |
| escalation | none |
| used by | sell |
| today | The sell cadence, unchanged |

### L12 · Approach cadence

| Parameter | Value |
|---|---|
| touches | 5 |
| schedule | day 2 · 4 · 8 · 12 · 26 |
| entry | Stage = Approach ∧ no reply |
| exit | they reply |
| on reply | → Stage Engaged · owner → Us · due +1 BD |
| on exhaust | one repeat after +14 days, then → Closed · Dropped |
| escalation | none |
| used by | fulfillment |
| today | F01 / F02 / FR01, merged into one object |

---

## 4. Buy-side

Nobridge helps someone buy a business. Inbound lead, nine stages, and a named loop at every point the other side can go quiet.

Business hours 09:00–18:00 Asia/Jakarta, Monday to Friday.

### Stages

| # | Stage | New? | What it means |
|---|---|---|---|
| 1 | Lead | **NEW** | It arrived. Nobody has worked it yet |
| 2 | Qualified | **NEW** | Screened, and worth the time |
| 3 | Intro Meeting | — | Meeting 1 · screening call |
| 4 | Strategy | — | Producing the strategy document |
| 5 | Strategy Review | — | Meeting 2 · walking them through it |
| 6 | Revamps | — | The revisions they asked for |
| 7 | Pitch | — | Meeting 3 · service evaluation |
| 8 | Negotiation | **NEW** | Terms, paperwork, signature |
| 9 | Closed | **NEW** | One terminal, four verdicts |

### Steps

#### Lead

**B01 · The record appears**

| Field | Value |
|---|---|
| trigger | A company is tagged Client Type = Buy side |
| timing | ~2 min |
| condition | — |
| writes | Stage = Lead · Stage Changed At = now · Source |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | runs on its own |

**B02 · Assign an owner**  `NEW`

| Field | Value |
|---|---|
| trigger | Owner is empty |
| timing | ≤ 15 min of creation |
| condition | — |
| writes | Owner = the assignee · Next Owner = Us · Next Action Due = +1 BD |
| owner | → Us · due +1 BD |
| exit | an owner is set |
| escalation | unassigned after 1 BD → the manager |
| who | runs on its own |

> New, and the one that makes the rest work. Nothing assigns a record today, so 'nobody owns it' is the normal state rather than an exception.

**B03 · Screen it**  `NEW`  → loop **L2**

| Field | Value |
|---|---|
| trigger | Stage = Lead ∧ Qualified is empty |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Qualified = true/false · Screening Notes |
| owner | → Us · due +1 BD |
| exit | qualified or disqualified |
| escalation | L2 — day 1 · 3 · 7, then Disqualified |
| who | by hand |

> New. Today a lead and a qualified lead are the same stage, which is why the board cannot tell you how many real opportunities are open.

**B04 · Promote to Qualified**

| Field | Value |
|---|---|
| trigger | Qualified = true |
| timing | on screening |
| condition | — |
| writes | Stage = Qualified · Stage Changed At = now |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Qualified

**B11 · Send the intro + booking link**

| Field | Value |
|---|---|
| trigger | Outreach Sent At is empty |
| timing | within 24 h · 09:00–18:00 |
| condition | Qualified = true |
| writes | Outreach Sent At = now |
| owner | → Them · due +2 BD |
| exit | they reply, or they book |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**B12 · Chase for a booking**  → loop **L1**

| Field | Value |
|---|---|
| trigger | Outreach Sent At set ∧ no meeting booked |
| timing | day 2 · 6 · 14 · 30 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | reply or booking |
| escalation | L1 exhausts → L9 |
| who | by hand |

**B14 · Promote to Intro Meeting**

| Field | Value |
|---|---|
| trigger | A meeting is BOOKED — not held |
| timing | on booking |
| condition | — |
| writes | Stage = Intro Meeting · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

> The BOOKING promotes; the call note records what happened to it. Two events, two moments, two fields.

#### Intro Meeting

**B21 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**B22 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**B23 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**B24 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**B25 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**B26 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**B27 · Promote to Strategy**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Strategy · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Strategy

**B31 · Agree the scope of the strategy document**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Strategy |
| timing | within 2 BD |
| condition | — |
| writes | Scope Agreed At = now |
| owner | → Us · due +2 BD |
| exit | scope written down |
| escalation | — |
| who | by hand |

> New. Today the clock starts at the stage move with nothing recording what was actually promised, which is how a deliverable slips without anyone disagreeing.

**B32 · Deliver the strategy document**  → loop **L5**

| Field | Value |
|---|---|
| trigger | Strategy Sent At is empty |
| timing | 10 days from the stage move · 09:00–18:00 |
| condition | Scope agreed |
| writes | Strategy Sent At = now |
| owner | → Us · due = the SLA |
| exit | it goes out |
| escalation | L5 — Escalated At at day 10, manager at day 13 |
| who | by hand |

> Never auto-completed: a sent email is not proof a document went out. That judgement held for the retired engine and still holds.

**B33 · Chase the next meeting**  → loop **L6**

| Field | Value |
|---|---|
| trigger | Strategy Sent At set ∧ no next meeting booked |
| timing | day 2 · 6 · 12 · 20 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | a meeting is booked |
| escalation | L6 exhausts → L9 |
| who | by hand |

**B34 · Promote to Strategy Review**

| Field | Value |
|---|---|
| trigger | The meeting is BOOKED — not held |
| timing | on booking |
| condition | — |
| writes | Stage = Strategy Review · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Strategy Review

**B41 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**B42 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**B43 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**B44 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**B45 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**B46 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**B47 · Promote to Revamps**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Revamps · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Revamps

**B51 · Agree the scope of the revamps**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Revamps |
| timing | within 2 BD |
| condition | — |
| writes | Scope Agreed At = now |
| owner | → Us · due +2 BD |
| exit | scope written down |
| escalation | — |
| who | by hand |

> New. Today the clock starts at the stage move with nothing recording what was actually promised, which is how a deliverable slips without anyone disagreeing.

**B52 · Deliver the revamps**  → loop **L5**

| Field | Value |
|---|---|
| trigger | Revamp Sent At is empty |
| timing | 7 days from the stage move · 09:00–18:00 |
| condition | Scope agreed |
| writes | Revamp Sent At = now |
| owner | → Us · due = the SLA |
| exit | it goes out |
| escalation | L5 — Escalated At at day 7, manager at day 10 |
| who | by hand |

> Never auto-completed: a sent email is not proof a document went out. That judgement held for the retired engine and still holds.

**B53 · Chase the next meeting**  → loop **L6**

| Field | Value |
|---|---|
| trigger | Revamp Sent At set ∧ no next meeting booked |
| timing | day 2 · 6 · 12 · 20 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | a meeting is booked |
| escalation | L6 exhausts → L9 |
| who | by hand |

**B54 · Promote to Pitch**

| Field | Value |
|---|---|
| trigger | The meeting is BOOKED — not held |
| timing | on booking |
| condition | — |
| writes | Stage = Pitch · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Pitch

**B61 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**B62 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**B63 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**B64 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**B65 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–18:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**B66 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**B67 · Promote to Negotiation**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Negotiation · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Negotiation

**B71 · Send the engagement letter**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Negotiation |
| timing | within 2 BD · 09:00–18:00 |
| condition | — |
| writes | Proposal Sent At = now |
| owner | → Them · due +3 days |
| exit | they respond |
| escalation | L5 |
| who | by hand |

**B72 · Chase the response**  `NEW`  → loop **L7**

| Field | Value |
|---|---|
| trigger | Proposal Sent At set ∧ no response |
| timing | day 3 · 7 · 14 · 21 · 09:00–18:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | terms agreed, or a decision |
| escalation | day 14 → the owner's manager |
| who | by hand |

**B73 · Work the redlines**  `NEW`

| Field | Value |
|---|---|
| trigger | They return comments |
| timing | within 2 BD |
| condition | — |
| writes | Terms Agreed At = now when settled |
| owner | → Us · due +2 BD |
| exit | terms settled |
| escalation | 3 rounds → the owner's manager |
| who | by hand |

> Drawn as its own step because it is the one that repeats invisibly. Three rounds of redlines is a different deal from one, and nothing records that.

**B74 · Out for signature**  `NEW`  → loop **L8**

| Field | Value |
|---|---|
| trigger | Terms Agreed At set |
| timing | day 2 · 5 · 10 · 20 · 09:00–18:00 |
| condition | — |
| writes | Signature Sent At = now · Contract Signed At on return |
| owner | → Them · due = the next touch |
| exit | signed |
| escalation | day 10 → the owner's manager |
| who | by hand |

**B75 · Close it won**

| Field | Value |
|---|---|
| trigger | Contract Signed At set |
| timing | same day |
| condition | — |
| writes | Stage = Closed · Final Decision = Closed Won · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

#### Closed

**B91 · Closed Lost**

| Field | Value |
|---|---|
| trigger | They say no |
| timing | on the decision |
| condition | — |
| writes | Final Decision = Closed Lost · Close Date = now · owner and due cleared |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

**B92 · No Decision Made**

| Field | Value |
|---|---|
| trigger | L3 or L7 ran out and they never came back |
| timing | on the loop ending |
| condition | — |
| writes | Final Decision = No Decision Made · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

> Reached only through a loop that actually ran. That is the whole meaning of the value, and it is why 40 buy deals carrying it at Stage 1 are wrong.

**B93 · Disqualified**  `NEW`

| Field | Value |
|---|---|
| trigger | Screening failed, or L2 ran out |
| timing | on judgement |
| condition | — |
| writes | Final Decision = Disqualified · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

> Replaces the Skipped stage. A verdict, not a position — which is what it always was.

**B94 · Do not contact**  `NEW`

| Field | Value |
|---|---|
| trigger | They ask not to be approached again |
| timing | immediately |
| condition | — |
| writes | Final Decision = Do Not Contact · Close Date = now |
| owner | cleared |
| exit | — terminal, and never re-entered |
| escalation | — |
| who | by hand |

> The only verdict here with a consequence outside the CRM. It must never feed L10, and today it has no field at all on Sell.

**B95 · Come back round**  `NEW`  → loop **L10**

| Field | Value |
|---|---|
| trigger | Final Decision = Follow Up (90) or (180) |
| timing | +90 days, then +180 |
| condition | Not Do Not Contact |
| writes | A fresh deal at Stage 2 if they bite |
| owner | → Them · due = the re-engage date |
| exit | they reply |
| escalation | — |
| who | by hand |

> The closed loop, finally with a mechanism. Designed in WORKFLOWS.md §8 and never built.

#### Any

**B13 · They reply**

| Field | Value |
|---|---|
| trigger | An inbound email from the point of contact |
| timing | instant |
| condition | — |
| writes | Replied At = now · every loop stops |
| owner | → Us · due +1 BD |
| exit | somebody answers it |
| escalation | unanswered 2 BD → the owner |
| who | by hand |

> The handover is the new part. Today a reply cancels every scheduled touch and schedules nothing back, which makes it the most dangerous event on the board.

**B80 · Park it as dormant**  → loop **L9**

| Field | Value |
|---|---|
| trigger | Any loop runs out |
| timing | on the loop ending |
| condition | — |
| writes | Progress Type = Ghosted · Next Action Due = +90 days |
| owner | → Them · due +90 days |
| exit | L9 re-engages it |
| escalation | — |
| who | by hand |

> Every loop feeds this, not just the cold one. That is the single biggest difference from today.

---

## 5. Sell-side

Cold outbound to potential sellers. Three entry stages instead of one, then the same spine as buy-side once somebody answers.

Business hours 08:00–17:00 Asia/Jakarta, Monday to Friday.

### Stages

| # | Stage | New? | What it means |
|---|---|---|---|
| 1 | Target | **NEW** | On the list. Nobody has touched it |
| 2 | Contacted | **NEW** | The cadence is running |
| 3 | Engaged | **NEW** | They answered |
| 4 | Intro Meeting | — | Meeting 1 · understanding what they need |
| 5 | Strategy | — | Producing the strategy document |
| 6 | Strategy Review | — | Meeting 2 |
| 7 | Revamps | — | The revisions |
| 8 | Pitch | — | Meeting 3 · service evaluation |
| 9 | Negotiation | **NEW** | Terms, paperwork, signature |
| 10 | Closed | **NEW** | One terminal, four verdicts |

### Steps

#### Target

**S01 · The record appears**

| Field | Value |
|---|---|
| trigger | A company is tagged Client Type = Sell side |
| timing | ~2 min |
| condition | — |
| writes | Stage = Target · Stage Changed At = now · Source |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | runs on its own |

> Target, not Stage 1. A company on the list is not a deal in progress, and today the board cannot tell the difference.

**S02 · Assign an owner**  `NEW`

| Field | Value |
|---|---|
| trigger | Owner is empty |
| timing | ≤ 15 min |
| condition | — |
| writes | Owner = the assignee |
| owner | → Us · due +1 BD |
| exit | an owner is set |
| escalation | 1 BD → the manager |
| who | runs on its own |

**S03 · Verify the contact**  `NEW`  → loop **L2**

| Field | Value |
|---|---|
| trigger | Stage = Target |
| timing | within 2 BD · 08:00–17:00 |
| condition | — |
| writes | Contact Verified At = now |
| owner | → Us · due +2 BD |
| exit | a named contact with a working address |
| escalation | L2 |
| who | by hand |

> New. Outbound to an unverified address is how a cadence burns six touches against a bounced mailbox and reads as a ghosting.

#### Contacted

**S04 · First reach-out**

| Field | Value |
|---|---|
| trigger | Contact verified ∧ Outreach Sent At is empty |
| timing | within 1 BD · 08:00–17:00 |
| condition | — |
| writes | Stage = Contacted · Outreach Sent At = now |
| owner | → Them · due +2 BD |
| exit | they reply |
| escalation | — |
| who | by hand |

**S05 · The cadence**  → loop **L11**

| Field | Value |
|---|---|
| trigger | Outreach Sent At set ∧ Replied At empty |
| timing | +2 BD · +5 BD · +14 d · +5 BD · +90 d · +3 BD · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they reply |
| escalation | L11 exhausts → Closed · No Decision Made |
| who | by hand |

> Running out is NOT do-not-contact. One is a ladder that ended and comes back round; the other is a company that asked us to stop.

#### Engaged

**S06 · They answer**  `NEW`

| Field | Value |
|---|---|
| trigger | An inbound reply |
| timing | instant |
| condition | — |
| writes | Stage = Engaged · Replied At = now · the cadence stops |
| owner | → Us · due +1 BD |
| exit | a meeting is booked |
| escalation | unanswered 2 BD → the owner |
| who | by hand |

> Engaged is a position now, not a timestamp. A seller who answers and then drifts is currently in a worse place than one who ignored us, because the one who ignored us is still on a ladder.

**S07 · Qualify the seller**  `NEW`  → loop **L2**

| Field | Value |
|---|---|
| trigger | Stage = Engaged ∧ Qualified is empty |
| timing | within 2 BD · 08:00–17:00 |
| condition | — |
| writes | Qualified = true/false |
| owner | → Us · due +2 BD |
| exit | qualified or disqualified |
| escalation | L2 |
| who | by hand |

**S08 · Chase for the intro meeting**  `NEW`  → loop **L1**

| Field | Value |
|---|---|
| trigger | Replied At set ∧ no meeting booked |
| timing | day 2 · 6 · 14 · 30 · 08:00–17:00 |
| condition | Qualified = true |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | a meeting is booked |
| escalation | L1 exhausts → L9 |
| who | by hand |

**S09 · Promote to Intro Meeting**

| Field | Value |
|---|---|
| trigger | A meeting is BOOKED |
| timing | on booking |
| condition | — |
| writes | Stage = Intro Meeting · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Intro Meeting

**S21 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**S22 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**S23 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**S24 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**S25 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**S26 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**S27 · Promote to Strategy**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Strategy · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Strategy

**S31 · Agree the scope of the strategy document**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Strategy |
| timing | within 2 BD |
| condition | — |
| writes | Scope Agreed At = now |
| owner | → Us · due +2 BD |
| exit | scope written down |
| escalation | — |
| who | by hand |

> New. Today the clock starts at the stage move with nothing recording what was actually promised, which is how a deliverable slips without anyone disagreeing.

**S32 · Deliver the strategy document**  → loop **L5**

| Field | Value |
|---|---|
| trigger | Strategy Sent At is empty |
| timing | 10 days from the stage move · 08:00–17:00 |
| condition | Scope agreed |
| writes | Strategy Sent At = now |
| owner | → Us · due = the SLA |
| exit | it goes out |
| escalation | L5 — Escalated At at day 10, manager at day 13 |
| who | by hand |

> Never auto-completed: a sent email is not proof a document went out. That judgement held for the retired engine and still holds.

**S33 · Chase the next meeting**  → loop **L6**

| Field | Value |
|---|---|
| trigger | Strategy Sent At set ∧ no next meeting booked |
| timing | day 2 · 6 · 12 · 20 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | a meeting is booked |
| escalation | L6 exhausts → L9 |
| who | by hand |

**S34 · Promote to Strategy Review**

| Field | Value |
|---|---|
| trigger | The meeting is BOOKED — not held |
| timing | on booking |
| condition | — |
| writes | Stage = Strategy Review · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Strategy Review

**S41 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**S42 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**S43 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**S44 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**S45 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**S46 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**S47 · Promote to Revamps**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Revamps · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Revamps

**S51 · Agree the scope of the revamps**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Revamps |
| timing | within 2 BD |
| condition | — |
| writes | Scope Agreed At = now |
| owner | → Us · due +2 BD |
| exit | scope written down |
| escalation | — |
| who | by hand |

> New. Today the clock starts at the stage move with nothing recording what was actually promised, which is how a deliverable slips without anyone disagreeing.

**S52 · Deliver the revamps**  → loop **L5**

| Field | Value |
|---|---|
| trigger | Revamp Sent At is empty |
| timing | 7 days from the stage move · 08:00–17:00 |
| condition | Scope agreed |
| writes | Revamp Sent At = now |
| owner | → Us · due = the SLA |
| exit | it goes out |
| escalation | L5 — Escalated At at day 7, manager at day 10 |
| who | by hand |

> Never auto-completed: a sent email is not proof a document went out. That judgement held for the retired engine and still holds.

**S53 · Chase the next meeting**  → loop **L6**

| Field | Value |
|---|---|
| trigger | Revamp Sent At set ∧ no next meeting booked |
| timing | day 2 · 6 · 12 · 20 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | a meeting is booked |
| escalation | L6 exhausts → L9 |
| who | by hand |

**S54 · Promote to Pitch**

| Field | Value |
|---|---|
| trigger | The meeting is BOOKED — not held |
| timing | on booking |
| condition | — |
| writes | Stage = Pitch · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Pitch

**S61 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**S62 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**S63 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**S64 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**S65 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 08:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**S66 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**S67 · Promote to Negotiation**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Negotiation · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Negotiation

**S71 · Send the engagement letter**  `NEW`

| Field | Value |
|---|---|
| trigger | Stage = Negotiation |
| timing | within 2 BD · 08:00–17:00 |
| condition | — |
| writes | Proposal Sent At = now |
| owner | → Them · due +3 days |
| exit | they respond |
| escalation | L5 |
| who | by hand |

**S72 · Chase the response**  `NEW`  → loop **L7**

| Field | Value |
|---|---|
| trigger | Proposal Sent At set ∧ no response |
| timing | day 3 · 7 · 14 · 21 · 08:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | terms agreed, or a decision |
| escalation | day 14 → the owner's manager |
| who | by hand |

**S73 · Work the redlines**  `NEW`

| Field | Value |
|---|---|
| trigger | They return comments |
| timing | within 2 BD |
| condition | — |
| writes | Terms Agreed At = now when settled |
| owner | → Us · due +2 BD |
| exit | terms settled |
| escalation | 3 rounds → the owner's manager |
| who | by hand |

> Drawn as its own step because it is the one that repeats invisibly. Three rounds of redlines is a different deal from one, and nothing records that.

**S74 · Out for signature**  `NEW`  → loop **L8**

| Field | Value |
|---|---|
| trigger | Terms Agreed At set |
| timing | day 2 · 5 · 10 · 20 · 08:00–17:00 |
| condition | — |
| writes | Signature Sent At = now · Contract Signed At on return |
| owner | → Them · due = the next touch |
| exit | signed |
| escalation | day 10 → the owner's manager |
| who | by hand |

**S75 · Close it won**

| Field | Value |
|---|---|
| trigger | Contract Signed At set |
| timing | same day |
| condition | — |
| writes | Stage = Closed · Final Decision = Closed Won · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

#### Closed

**S91 · Closed Lost**

| Field | Value |
|---|---|
| trigger | They say no |
| timing | on the decision |
| condition | — |
| writes | Final Decision = Closed Lost · Close Date = now · owner and due cleared |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

**S92 · No Decision Made**

| Field | Value |
|---|---|
| trigger | L3 or L7 ran out and they never came back |
| timing | on the loop ending |
| condition | — |
| writes | Final Decision = No Decision Made · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

> Reached only through a loop that actually ran. That is the whole meaning of the value, and it is why 40 buy deals carrying it at Stage 1 are wrong.

**S93 · Disqualified**  `NEW`

| Field | Value |
|---|---|
| trigger | Screening failed, or L2 ran out |
| timing | on judgement |
| condition | — |
| writes | Final Decision = Disqualified · Close Date = now |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

> Replaces the Skipped stage. A verdict, not a position — which is what it always was.

**S94 · Do not contact**  `NEW`

| Field | Value |
|---|---|
| trigger | They ask not to be approached again |
| timing | immediately |
| condition | — |
| writes | Final Decision = Do Not Contact · Close Date = now |
| owner | cleared |
| exit | — terminal, and never re-entered |
| escalation | — |
| who | by hand |

> The only verdict here with a consequence outside the CRM. It must never feed L10, and today it has no field at all on Sell.

**S95 · Come back round**  `NEW`  → loop **L10**

| Field | Value |
|---|---|
| trigger | Final Decision = Follow Up (90) or (180) |
| timing | +90 days, then +180 |
| condition | Not Do Not Contact |
| writes | A fresh deal at Stage 2 if they bite |
| owner | → Them · due = the re-engage date |
| exit | they reply |
| escalation | — |
| who | by hand |

> The closed loop, finally with a mechanism. Designed in WORKFLOWS.md §8 and never built.

#### Any

**S80 · Park it as dormant**  → loop **L9**

| Field | Value |
|---|---|
| trigger | Any loop runs out |
| timing | on the loop ending |
| condition | — |
| writes | Progress Type = Ghosted · Next Action Due = +90 days |
| owner | → Them · due +90 days |
| exit | L9 re-engages it |
| escalation | — |
| who | by hand |

---

## 6. Fulfillment

Approaching targets for a live sell-side mandate. Nine stages, and for the first time a loop on every one of them.

Business hours 09:00–17:00 Asia/Jakarta, Monday to Friday.

### Stages

| # | Stage | New? | What it means |
|---|---|---|---|
| 1 | Approach | **NEW** | Teaser out. No answer yet |
| 2 | Engaged | **NEW** | They answered |
| 3 | Meeting 1 | — | Intro call |
| 4 | NDA | — | Out for signature |
| 5 | Meeting 2 | — | First real conversation about numbers |
| 6 | Due Diligence | — | The data room is open to them |
| 7 | Meeting 3 | — | Post-diligence |
| 8 | Offer Expected | **NEW** | They said an offer is coming |
| 9 | Closed | **NEW** | Offer Received · Passed · Dropped |

### Steps

#### Approach

**F01 · The record appears**

| Field | Value |
|---|---|
| trigger | Tagged Client Type = Fulfillment, or a mandate list import |
| timing | ~2 min |
| condition | — |
| writes | Stage = Approach · Mandate · Stage Changed At = now |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | runs on its own |

**F02 · Assign an owner**  `NEW`

| Field | Value |
|---|---|
| trigger | Owner is empty |
| timing | ≤ 15 min |
| condition | — |
| writes | Owner = the assignee |
| owner | → Us · due +1 BD |
| exit | an owner is set |
| escalation | 1 BD → the manager |
| who | runs on its own |

**F03 · Send the teaser**

| Field | Value |
|---|---|
| trigger | Stage = Approach ∧ Outreach Sent At empty |
| timing | within 2 BD · 09:00–17:00 |
| condition | The mandate is live |
| writes | Outreach Sent At = now |
| owner | → Them · due +2 days |
| exit | they reply |
| escalation | — |
| who | by hand |

**F04 · The approach cadence**  → loop **L12**

| Field | Value |
|---|---|
| trigger | Outreach Sent At set ∧ no reply |
| timing | day 2 · 4 · 8 · 12 · 26 · 09:00–17:00 |
| condition | — |
| writes | Follow-up Date = the next touch |
| owner | → Them · due = the next touch |
| exit | they reply |
| escalation | one repeat after +14 d, then Closed · Dropped |
| who | by hand |

> F01, F02 and FR01 collapse into one loop with a repeat count. Same behaviour, one object instead of three plays that had to be read together.

#### Engaged

**F05 · They answer**  `NEW`

| Field | Value |
|---|---|
| trigger | An inbound reply |
| timing | instant |
| condition | — |
| writes | Stage = Engaged · Replied At = now · the cadence stops |
| owner | → Us · due +1 BD |
| exit | a meeting is booked |
| escalation | unanswered 2 BD → the owner |
| who | by hand |

**F06 · Qualify the interest**  `NEW`  → loop **L2**

| Field | Value |
|---|---|
| trigger | Stage = Engaged |
| timing | within 2 BD · 09:00–17:00 |
| condition | — |
| writes | Qualified = true/false · Prospect Type confirmed |
| owner | → Us · due +2 BD |
| exit | qualified or dropped |
| escalation | L2 |
| who | by hand |

**F07 · Promote to Meeting 1**

| Field | Value |
|---|---|
| trigger | The intro meeting is BOOKED |
| timing | on booking |
| condition | — |
| writes | Stage = Meeting 1 · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

> Meeting Outcome does not exist on this board today, so a fulfillment no-show has no state and no recovery.

#### Meeting 1

**F11 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**F12 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**F13 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**F14 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**F15 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**F16 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**F17 · Promote to NDA**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = NDA · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### NDA

**F20 · Send the NDA**

| Field | Value |
|---|---|
| trigger | Stage = NDA |
| timing | within 1 BD · 09:00–17:00 |
| condition | — |
| writes | NDA Sent At = now |
| owner | → Them · due +2 days |
| exit | signed |
| escalation | — |
| who | by hand |

**F21 · Chase the signature**  `NEW`  → loop **L8**

| Field | Value |
|---|---|
| trigger | NDA Sent At set ∧ NDA Signed At empty |
| timing | day 2 · 5 · 10 · 20 · 09:00–17:00 |
| condition | — |
| writes | Follow-up Date = the next touch |
| owner | → Them · due = the next touch |
| exit | NDA Signed At = now |
| escalation | day 10 → the owner's manager |
| who | by hand |

> New. An NDA that goes out and is never signed is currently indistinguishable from one that came back the same afternoon.

**F22 · Promote to Meeting 2**

| Field | Value |
|---|---|
| trigger | The second meeting is BOOKED |
| timing | on booking |
| condition | NDA signed |
| writes | Stage = Meeting 2 · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Meeting 2

**F31 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**F32 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**F33 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**F34 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**F35 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**F36 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**F37 · Promote to Due Diligence**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Due Diligence · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Due Diligence

**F40 · Open the data room**

| Field | Value |
|---|---|
| trigger | Stage = Due Diligence |
| timing | within 2 BD · 09:00–17:00 |
| condition | NDA signed |
| writes | VDR Opened At = now |
| owner | → Them · due +7 days |
| exit | they engage with it |
| escalation | — |
| who | by hand |

**F41 · Check they are actually in it**  `NEW`  → loop **L3**

| Field | Value |
|---|---|
| trigger | VDR Opened At set ∧ no activity in 7 days |
| timing | day 7 · 14 · 21 · 09:00–17:00 |
| condition | — |
| writes | Follow-up Date = the next touch |
| owner | → Them · due = the next touch |
| exit | activity, or a question |
| escalation | L3 exhausts → hand back for a decision |
| who | by hand |

> New, and the longest stage on the board. A data room nobody opens looks exactly like one being read carefully.

**F42 · Promote to Meeting 3**

| Field | Value |
|---|---|
| trigger | The third meeting is BOOKED |
| timing | on booking |
| condition | — |
| writes | Stage = Meeting 3 · Meeting Outcome = Scheduled |
| owner | → Us · due +1 BD |
| exit | — |
| escalation | — |
| who | by hand |

#### Meeting 3

**F51 · Send confirmation + agenda**  `NEW`

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Scheduled |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Agenda Sent At = now |
| owner | → Them · due = the meeting date |
| exit | the meeting date arrives |
| escalation | not sent by the day before → the owner |
| who | by hand |

> Stamped, unlike today — A02 currently writes nothing, so after the fact nobody can tell whether the agenda went out.

**F52 · The call is written up**

| Field | Value |
|---|---|
| trigger | The Meet call ends and its Gemini notes are ingested |
| timing | ≤ 15 min |
| condition | The event has a Meet link |
| writes | Meeting Outcome = Hosted · note on Company, Contact and deal |
| owner | → Us · due +1 BD |
| exit | the note is filed |
| escalation | no notes document → flag on the Calls tab |
| who | runs on its own |

> Call Intelligence. The only step on this chart that runs on its own today.

**F53 · Approve the follow-ups**  `NEW`

| Field | Value |
|---|---|
| trigger | Action items queued by the write-up |
| timing | within 1 BD |
| condition | — |
| writes | CRM tasks, once approved |
| owner | → Us · due +1 BD |
| exit | approved or dismissed |
| escalation | unapproved after 3 days → the owner |
| who | approve on the Calls tab |

> The expiry is new. Today an unapproved item sits in the queue for ever.

**F54 · Recover a missed meeting**  → loop **L4**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = No-show, Rescheduled or Cancelled |
| timing | immediately |
| condition | — |
| writes | Meeting Outcome = Scheduled once re-booked |
| owner | → Them · due = the next touch |
| exit | re-booked |
| escalation | L4 exhausts → L9 |
| who | by hand |

> Cancellations now get the same four touches a no-show gets. Today they get one re-confirm and then silence.

**F55 · Send the recap**

| Field | Value |
|---|---|
| trigger | Meeting Outcome = Hosted |
| timing | within 24 h · 09:00–17:00 |
| condition | — |
| writes | Recap Sent At = now |
| owner | → Them · due +2 BD |
| exit | they respond to it |
| escalation | 24 h late → Escalated At = now |
| who | by hand |

**F56 · Chase the go-ahead**  → loop **L3**

| Field | Value |
|---|---|
| trigger | Recap Sent At set ∧ the next step is not agreed |
| timing | day 2 · 6 · 12 · 20 · 09:00–17:00 |
| condition | — |
| writes | Next Action Due = the next touch |
| owner | → Them · due = the next touch |
| exit | they agree, or they reply |
| escalation | L3 exhausts → L9 |
| who | by hand |

> A recap is not a yes. This is the gap that used to leave a deal at Hosted with nobody owing anything.

**F57 · Promote to Offer Expected**

| Field | Value |
|---|---|
| trigger | They agree to the next piece of work |
| timing | on their agreement |
| condition | — |
| writes | Stage = Offer Expected · Stage Changed At = now |
| owner | → Us · due per the next stage's SLA |
| exit | — |
| escalation | — |
| who | by hand |

#### Offer Expected

**F60 · Record the expected offer**  `NEW`

| Field | Value |
|---|---|
| trigger | They confirm an offer is being prepared |
| timing | same day |
| condition | — |
| writes | Stage = Offer Expected · Offer Expected By = their date |
| owner | → Them · due = their stated date |
| exit | the offer lands |
| escalation | — |
| who | by hand |

> Their date, written down. Today this stage means 'waiting' with nothing recording what we are waiting for or until when.

**F61 · Chase the offer**  `NEW`  → loop **L7**

| Field | Value |
|---|---|
| trigger | Offer Expected By has passed |
| timing | day 3 · 7 · 14 · 21 · 09:00–17:00 |
| condition | — |
| writes | Follow-up Date = the next touch |
| owner | → Them · due = the next touch |
| exit | an offer, or a pass |
| escalation | L7 exhausts → Closed · Dropped |
| who | by hand |

> The expiry this stage has never had. It is the rung that needs one most, because waiting is its entire meaning.

#### Closed

**F70 · Close it out**

| Field | Value |
|---|---|
| trigger | An offer lands, they pass, or they go dark for good |
| timing | on the outcome |
| condition | — |
| writes | Stage = Closed · Outcome = Offer Received \| Passed \| Dropped · owner cleared |
| owner | cleared |
| exit | — |
| escalation | — |
| who | by hand |

#### Any

**F71 · The mandate ends**  `NEW`

| Field | Value |
|---|---|
| trigger | The sell deal this Mandate points at gets a Final Decision |
| timing | same day |
| condition | The record is still open |
| writes | Outcome set on every open record on that mandate · owner cleared |
| owner | cleared |
| exit | — |
| escalation | anyone mid-conversation is told |
| who | by hand |

> New, and the only rule here with a real counterparty on the other end. A target in Due Diligence for a mandate that closed in March looks exactly like a live one.

---

## 7. Migration

| Board | Today | Becomes | Rule | Records |
|---|---|---|---|---|
| buy | Stage 1 · New Lead | Lead or Qualified | Outreach Sent At empty → Lead; set → Qualified | 99 to split |
| buy | Stages 2–6 | Intro Meeting → Pitch | One to one, in order | no change |
| buy | Completed / Skipped | Closed | The verdict already says which; Skipped becomes Disqualified | merged |
| buy | — | Negotiation | Forward-only. No record migrates in | 0 |
| sell | Stage 1 · New Lead | Target, Contacted or Engaged | No outreach → Target; sent → Contacted; Replied At set → Engaged | 35 to split |
| sell | Stages 2–6 | Intro Meeting → Pitch | One to one | no change |
| sell | Closed Won | Closed | The verdict carries the outcome | merged |
| fulfillment | Reached Out / Teaser | Approach or Engaged | Replied At set → Engaged | 348 to split |
| fulfillment | Meeting 1 → Meeting 3 | unchanged | One to one | no change |
| fulfillment | Waiting on Offer | Offer Expected | Rename, plus an expiry date | rename |
| other | All stages | Follows Buy | 5 records, Buy's rules with Sell's verdicts | 5 |

## 8. What it costs

487 records re-staged, every board layout and saved view rebuilt, and clienttype-sync updated because it creates records at a named stage. This is the expensive option — restructuring stages moves everything that points at them. Nothing here is additive-only the way a new field would be.

## 9. What it does not fix

Nothing here makes the CRM understand a conversation. Whether a deal is genuinely alive is still a judgement; this only guarantees somebody has been asked to make it, and that no record can sit with nothing scheduled. Call Intelligence remains the only step on any of these charts that runs on its own today.

