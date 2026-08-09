# What changed on the CRM boards

*Applied Sunday 9 August 2026, early afternoon. **This is live now** — open a board and you'll see it.*

---

## The short version

The deal boards now have **more stages** and **a few new fields**, so the board shows things it
previously couldn't: whether a lead has actually been screened, and where a deal is between "we
pitched" and "it's closed".

Your deals, notes, contacts, companies and call records were **not** affected. Nothing was deleted.
Every deal kept its history and landed on the stage that means the same thing it meant before.

**One thing needs your attention:** if you create a deal and don't pick a stage, it now arrives with
**no stage at all** and won't show up on the board until you set one. See *[Two things to know](#two-things-to-know)*.

---

## Your board, before and after

### Buy side — 8 columns become 9

| Today | Becomes |
|---|---|
| Stage 1 · New Lead | **Lead** → or **Qualified** ⭐ |
| Stage 2 · Intro Meeting + Screening | Intro Meeting |
| Stage 3 · Strategy / Value Creation | Strategy |
| Stage 4 · Strategy Review | Strategy Review |
| Stage 5 · Revamps | Revamps |
| Stage 6 · Service Evaluation + Pitch | Pitch |
| *(nothing)* | **Negotiation** ⭐ |
| Completed / Skipped | Closed |

### Sell side — 7 columns become 10

| Today | Becomes |
|---|---|
| Stage 1 · New Lead | **Target** → **Contacted** → **Engaged** ⭐ |
| Stage 2 → Stage 6 | Intro Meeting · Strategy · Strategy Review · Revamps · Pitch |
| *(nothing)* | **Negotiation** ⭐ |
| Closed Won | Closed |

### Fulfillment — 7 columns become 9

| Today | Becomes |
|---|---|
| Reached Out / Teaser | **Approach** → **Engaged** ⭐ |
| Meeting 1 · NDA · Meeting 2 · Due Diligence · Meeting 3 | unchanged |
| Waiting on Offer | **Offer Expected** |
| *(nothing)* | Closed |

### ⭐ The two that are genuinely new

**Qualified** *(and Contacted / Engaged on sell side)* — right now "New Lead" means two different
things at once: a lead that just arrived, and a lead you've been chasing for three weeks. They need
completely different work, and the board can't tell them apart. Now it can.

**Negotiation** — today a deal jumps straight from Pitch to Closed. Everything in between — the
engagement letter, the terms, the back-and-forth on the contract, the signature — happens with the
deal parked on Pitch, invisible. That's often six weeks of real work that the board simply doesn't
show.

---

## Where your deals landed

**449 deals moved. 487 in total, none lost.**

**Buy side · 99 deals**

| | |
|---|---|
| 48 | New Lead → **Lead** |
| 34 | Stage 2 → **Intro Meeting** |
| 8 | Completed / Skipped → **Closed** |
| 7 | Stage 3 → **Strategy** *(name changed, column didn't move)* |
| 2 | Stage 6 → **Pitch** |

**Sell side · 35 deals** — 32 → **Pitch**, 1 → **Intro Meeting**, 1 → **Closed**, 1 → **Target**.

**Fulfillment · 348 records** — 317 → **Approach**, 4 stayed where they were, 27 have no stage set
and were left alone.

**Other opportunities · 5 deals** — all → **Lead**.

Nothing landed in **Negotiation**. It starts empty on purpose — back-dating deals into a stage they
never went through would invent a history that didn't happen.

---

## What's new on a deal

The useful ones:

- **Qualified** — has this lead actually been screened, yes or no.
- **Next owner** — whose move is it: **us** or **them**. This is the one that changes how the
  board reads. "Overdue, and it's our move" means we owe someone a document. "Overdue, and it's
  theirs" means chase them. Today both look identical: a quiet deal.
- **Next action due** — the date that move is due by.
- **Stamps for the things nobody records today** — when the agenda went out, when the proposal
  went out, when it went for signature, when it came back signed.

---

## The one thing you'll do differently

> **Every open deal says who owes the next move, and by when.**
> If you can't say what happens next, the deal isn't open — close it.

That's it. It's deliberately a small amount of friction, at the exact moment where the alternative
is a deal going quiet and nobody noticing for four months.

---

## Two things to know

**A new deal with no stage won't appear on the board.** The boards used to quietly file any new deal
under "New Lead" if you didn't pick a stage. That default had to be removed to retire the old
columns, and it wasn't replaced — so a deal created without a stage now has none, and the kanban
won't show it. Pick a stage when you create a deal, or create it by dragging into a column. If a
deal seems to have vanished, look at the board's table view: it's there, with an empty Stage.

*Tagging a company still works as it always did* — that creates the deal in the first column
(**Lead**, **Target** or **Approach**) automatically.

## What looks odd, and isn't broken

**Every buy lead is in Lead — none in Qualified.** The split reads a date that records when outreach
went out, and that date is empty on every deal (it was cleared when the old automation was switched
off in August). So the column exists, but it can't sort anything until people start recording
outreach again. Same story for Approach vs Engaged on the Fulfillment board.

**Negotiation is empty.** See above — that's on purpose.

**Some deals changed column name without moving.** "Stage 3 · Strategy" is simply "Strategy" now.
Same deals, same place, shorter name.

**The column colours don't run in a neat gradient.** Cosmetic only, and left alone deliberately
rather than recolouring columns nobody asked to have recoloured. The *order* is correct.

---

## What did not change

Companies · contacts · notes · call recordings and summaries · attachments · emails · calendar
events · deal names · amounts · owners · every deal's history and activity feed.

No deal was deleted, merged, or renamed.

---

## Questions you might have

**Did I lose anything?**
No. All 487 deals are accounted for and every one is on a stage that means what its old stage meant.
An automated check confirmed that before the old columns were removed, and every step was recorded
beforehand so it could be put back.

**Did it go smoothly?**
Mostly. Three steps were rejected by the CRM on the first attempt and had to be corrected before
they'd run — each failed cleanly without half-changing anything, which is why you didn't notice. One
genuine mistake got through and was fixed the same afternoon: for a few minutes the columns were in
the wrong order on every board.

**Do I need to do anything?**
Two things. Pick a stage when you create a deal (see above). And start filling in **Next owner** and
**Next action due** on your open deals — nothing fills those in for you, and they're the point of
the whole change.

**Where do I read the actual rules?**
[`WORKFLOWS.md`](./WORKFLOWS.md) describes the pipeline in full, and the **High Level Workflows**
and **Workflow** tabs on node.nobridge.co draw it. Those now match the boards — which they didn't
before today. `_archive/WORKFLOWS-pre-v2.md` describes the old six-stage boards and is history now;
don't work deals from it.
