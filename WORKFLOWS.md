# Nobridge pipeline workflows — reference

> **Status: RETIRED 2026-08-07.** The buy-side, sell-side and fulfillment rules engines no longer
> run. Nothing in this document is live. It is kept because the *rules* — when we owe a response,
> how long a chase runs, when a prospect is considered ghosted — are business knowledge worth
> keeping even though the machine that enforced them is gone.
>
> **Why they were retired:** the engine matched on stage and timestamps only. It had no
> understanding of what was actually said in a conversation, so its tasks were noise. It produced
> 433 tasks in the CRM, all of which were deleted on retirement.
>
> The rules below are transcribed from the engine source, which is preserved (dormant) at
> `Desktop/Nobridge Software/Sales Engine VM`. Nothing here contains customer data.
>
> **Prefer a picture?** Each of the three pipelines is also drawn as a flowchart — every play,
> decision, chase loop and re-engage cycle, start to end. On the ops dashboard:
> **node.nobridge.co → Workflows → Show chart**. Source: `.crm-automations/dashboard/workflow_charts.py`.

---

## Shared settings

| Setting | Value |
|---|---|
| Timezone | `Asia/Jakarta` |
| Business hours | 09:00–18:00, all three pipelines |
| Business days | Monday–Friday |
| Reconcile cadence | every 5 min (state re-derived from the CRM) |
| Tick cadence | every 60 s (due work fired) |

Every scheduled touch was "snapped" into the next business-hours window, so nothing fired at
02:00 on a Sunday. Day offsets marked **BD** are business days; plain day counts are calendar days.

---

## Buy-side

Deals where Nobridge helps someone buy a business.

### Internal SLAs — things *we* owed

| ID | Play | Trigger | Rule |
|---|---|---|---|
| **A01** | Answer a new lead | New lead, no outreach sent | Task due immediately; **24 h SLA**. Missing it stamped an overdue escalation on the deal. Completing it stamped `outreachSentAt`. |
| **A02** | Confirmation + agenda | Meeting booked | Task due immediately; **24 h SLA**. |
| **A03** | Meeting recap | Meeting hosted | Task due immediately; **24 h SLA**. Completing it stamped `recapSentAt`. |
| **A04** | Strategy document | Entered Strategy stage | **10-day** deliverable SLA; task due on day 10, escalation at day 10. Stamped `strategySentAt`. |
| **A05** | Revamps | Entered Revamps stage | **7-day** deliverable SLA; task due on day 7, escalation at day 7. Stamped `revampSentAt`. |

A01/A02/A03 auto-completed when an outbound email to the contact was detected. **A04 and A05
never did** — a sent email is not proof the document went out, so they were closed by hand.

### External chases — them going quiet

| ID | Play | Trigger | Ladder |
|---|---|---|---|
| **B01** | Chase before booking | Outreach sent, no meeting booked | Cold ladder: **days 2, 6, 14, 30**. Exhausted → dormant → C01. |
| **B02** | No-show recovery | Meeting outcome = No Show | Immediate reschedule task, then the same cold ladder. |
| **B03** | Warm follow-up (Mtg 2) | Strategy doc sent, no next meeting | Warm ladder: **days 2, 6, 12, 20**. |
| **B04** | Warm follow-up (Mtg 3) | Revamps sent, no next meeting | Warm ladder: **days 2, 6, 12, 20**. |
| **C01** | 90-day re-engage | Dormant | One fresh reach-out at **+90 days**, then a bump at **+7 days** (day 97) if still silent. |

Only one chase task was ever open at a time per play; each new touch cancelled the previous one.

### Interrupts and cleanup

| ID | Play | Rule |
|---|---|---|
| **D01** | Reply intercept | The moment a reply landed: cancel B01–B04 and C01, raise one task — *review & respond*. |
| **D02** | Lost cleanup | Deal lost / ghosted / DNC → cancel every open task and pending job. |
| **D03** | Won cleanup | Deal won → cancel every open task and pending job. |
| **D04** | Rescheduled meeting | Meeting rescheduled or cancelled → re-confirm task, **24 h SLA**. |

### Stage → active play

| Stage : sub-state | Active |
|---|---|
| `NEW_LEAD : AWAITING_OUTREACH` | A01 |
| `NEW_LEAD : AWAITING_BOOKING` | B01 |
| `MEETING_1/2/3 : SCHEDULED` | A02 |
| `MEETING_1/2/3 : NO_SHOW` | B02 |
| `MEETING_1/2/3 : HOSTED` | A03 |
| `MEETING_1/2/3 : RESCHEDULED` | D04 |
| `STRATEGY : AWAITING_DOC` | A04 |
| `STRATEGY : AWAITING_BOOKING` | B03 |
| `REVAMPS : AWAITING_REVAMP` | A05 |
| `REVAMPS : AWAITING_BOOKING` | B04 |
| `DORMANT : HELD_OFF` | C01 |
| `CLOSED_WON : TERMINAL` | D03 |
| `LOST : TERMINAL` | D02 |

Sub-state was derived from the deal's own fields — e.g. New Lead split on whether outreach had
been stamped; a meeting stage split on its meeting outcome.

---

## Sell-side

Outbound to potential sellers. One fixed ladder that stopped the second someone answered.

| ID | Play | Rule |
|---|---|---|
| **S01** | First reach-out | No outreach stamped → one task, timed into business hours. |
| **S02** | The cadence | The six-step ladder below. |
| **SD01** | Reply intercept | Reply → cancel everything, mark *In Discussions / Scheduled*, raise one task: *meet to understand needs*. |
| **ST01** | Closed cleanup | Won, lost, or DNC → cancel all open tasks and jobs. |

### The sell cadence

Each step fired only if there had been no reply since the previous touch.

| # | Step | Delay from previous | Marked on the deal when entering |
|---|---|---|---|
| 1 | 2nd reach-out | **+2 BD** | — |
| 2 | 3rd reach-out | **+5 BD** | — |
| 3 | Ghosted — re-engage | **+14 days** | `progressType = GHOSTED` |
| 4 | Re-engage follow-up | **+5 BD** | — |
| 5 | 3-month re-engage | **+90 days** | `engagementStatus = HELD_OFF` |
| 6 | 3-month re-engage (2nd) | **+3 BD** | — |
| — | Ladder exhausted | — | `engagementStatus = CRASH_OUT_DNC`, deal parked |

> Steps 3, 5 and the exhaustion step wrote real status values onto deals. **Those were automation
> output, not a person's judgement** — 16 deals carry `GHOSTED` and 5 carry `HELD_OFF` from this
> ladder. They were left in place at retirement.

### Stage → active play

| Stage : sub-state | Active | Meaning |
|---|---|---|
| `NEW : AWAITING_OUTREACH` | S01 | Genuinely cold |
| `ACTIVE : CHASE` | S02 | Outreach sent, awaiting reply |
| `ENGAGED : PASSIVE` | — | Already replied / in discussions / held off / ghosted — never cold-started |
| `TERMINAL : DONE` | ST01 | Closed or DNC |

---

## Fulfillment

Clients being actively delivered for.

| ID | Play | Rule |
|---|---|---|
| **F01** | No-response chase | Client quiet → ladder below. |
| **F02** | Engaged nudges | Client actively speaking → same ladder, gentler framing. |
| **FD01** | Reply intercept | Reply → cancel all chases, raise one *review & respond* task. |
| **FT01** | Completion cleanup | Outcome recorded, or progress = Complete → close everything out. |

### The fulfillment ladder

Cumulative day offsets **2, 4, 8, 12, 26** — gaps of 2, 2, 4, 4, then 14.

Run twice: the initial cycle, then — if still silent — a **+14-day** re-engagement that repeats the
same ladder once. After the second cycle exhausts, chasing stops and the record is left for manual
handling.

### Stage → active play

| Stage : sub-state | Active |
|---|---|
| `ACTIVE : CHASE` | F01 (no reply yet, or ghosted) |
| `ACTIVE : ENGAGED` | F02 (actively speaking) |
| `TERMINAL : DONE` | FT01 |

> Naming trap worth remembering: on fulfillment records the field labelled **"Progress Type"** in
> the CRM UI is `engagementStatus` underneath — not `progressType`, which is what the buy and sell
> boards use.

---

## Status buckets

The engine projected every tracked record into one of eight buckets. These drove the (now removed)
Overview and Pipeline views, and are a decent vocabulary for thinking about a pipeline by hand.

| Bucket | Meaning |
|---|---|
| Needs response | They replied — the ball is in our court. |
| Meeting booked | Meeting booked — send confirmation + agenda. |
| On task | We owe an internal deliverable (doc, recap…). |
| Follow-up due | A chase touch is open — reach out. |
| Waiting on them | Next touch already scheduled; nothing to do right now. |
| Dormant | Parked — a re-engage play would pick it up. |
| No automation | Human-managed; the engine only watched. |
| Closed | Won, lost, or do-not-contact. |

---

## Task titles the engine produced

Useful for recognising leftovers. All of these were deleted on 2026-08-07.

**Buy-side** — `Respond to new lead: {n} (intro + booking link)` · `Send confirmation + agenda: {n} (Mtg {k})` ·
`Send recap / summary: {n} (Mtg {k})` · `Produce + send strategy doc: {n}` · `Deliver revamps: {n}` ·
`Follow up, no booking yet: {n} (touch {i})` · `Reschedule no-show: {n} (Mtg {k})` ·
`Follow up to rebook: {n} (touch {i})` · `Follow up to book Mtg 2: {n} (touch {i})` ·
`Follow up to book Mtg 3: {n} (touch {i})` · `Re-engage, new thread: {n}` · `Re-engage bump: {n}` ·
`Re-confirm rescheduled meeting: {n} (Mtg {k})` · `Reply in — review & respond: {n}`

**Sell-side** — `Reach out to {n} (1st)` · `2nd reach-out: {n}` · `3rd reach-out: {n}` ·
`Ghosted — re-engage (2 weeks): {n}` · `Re-engage follow-up: {n}` · `3-month re-engage: {n}` ·
`3-month re-engage (2nd): {n}` · `Reply in — meet to understand needs: {n}`

**Fulfillment** — `Follow up (no response): {n} (touch {i})` · `Keep {n} moving to the next step (touch {i})` ·
`Re-engage: {n} (touch {i})` · `Reply in — review & respond: {n}`

Task bodies carried a one-line prefix — `Buy-side:`, `Sell-side:` or `Fulfillment:` — which is what
distinguished them from Call Intelligence tasks.

---

## Where the source lives

| Rule set | File (in `Desktop/Nobridge Software/Sales Engine VM`) |
|---|---|
| Buy plays + task titles | `src/automations/registry.ts` |
| Buy ladders + SLAs | `src/automations/patterns.ts` |
| Sell cadence table | `src/automations/sellPatterns.ts` (`SELL_CADENCE`) |
| Fulfillment ladder | `src/automations/fulfillmentPatterns.ts` (`CHASE_OFFSETS`) |
| Stage → play tables | `src/core/stateMachine.ts`, `sellStateMachine.ts`, `fulfillmentStateMachine.ts` |
| Completion → CRM stamp | `src/core/taskManager.ts` (`COMPLETION_FIELD`) |
| Business hours | `src/config.ts` |
| Plain-English version | `.crm-automations/dashboard/dashboard.py` (`CATALOG`), rendered on the dashboard's Workflows tab |

Historical engine state (lead states, job queue, task ledger, bucket history) was exported to JSON
before the wipe and lives with the retirement backups — **outside this repo**, since it contains
contact names and email addresses.
