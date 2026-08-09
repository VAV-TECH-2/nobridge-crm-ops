"""The target CRM schema for the v2 workflow — DERIVED from the dashboard's workflow_spec.

Nothing is typed twice. The stage option sets come straight from `PIPELINES[side]["stages"]`, so a
stage renamed in the spec is renamed here, in both charts and in WORKFLOWS.md at once. The field
list is the one place this file adds something the spec does not carry: a CRM *type* for each
field the steps write.

⚠ NOTHING HERE HAS BEEN APPLIED. Every script in this folder is dry-run by default.

Boards
------
`otherOpportunity` follows Buy (5 records, WORKFLOWS.md §2.1) and so takes Buy's stage set.
`networking` is out of scope — it has no chase ladder and never had one.
"""
import os
import sys

# The spec lives with the dashboard; this is the only place that reaches across for it, and it is
# a read. Keeping one copy is the entire point — a second stage list here would be the fifth
# hand-kept copy of the thing that just got reduced to one.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".crm-automations", "dashboard"))
import workflow_spec as ps  # noqa: E402

# Which API object each pipeline maps to. Buy's rules also drive otherOpportunity.
OBJECTS = {
    "buy": ["buyOpportunity", "otherOpportunity"],
    "sell": ["sellOpportunity"],
    "fulfillment": ["fulfillment"],
}

# ── Fields ──────────────────────────────────────────────────────────────────
# `(label, type, objects, note)`. Types are Twenty's FieldMetadataType values. Everything here is
# ADDITIVE — no existing field is altered or removed by 01_add_fields.
OPP = ["buyOpportunity", "sellOpportunity", "otherOpportunity"]
ALL4 = OPP + ["fulfillment"]

NEW_FIELDS = [
    ("Qualified", "BOOLEAN", ALL4,
     "Screening outcome. Splits 'a lead arrived' from 'a lead worth working' — the two things "
     "Stage 1 currently means at once."),
    ("Next Owner", "SELECT", ALL4,
     "Us | Them. Which SIDE owes the next move, not who at Nobridge owns the deal — the record "
     "already answers that. It is what separates a delivery failure from a chase."),
    ("Next Action Due", "DATE_TIME", ALL4,
     "By when. Generalises Next Reach-Out At (Sell only) and Follow-up Date (Fulfillment only); "
     "Buy, with 99 records, has neither today."),
    ("Stage Changed At", "DATE_TIME", ALL4,
     "Time-in-stage, currently unknowable for every record on every board."),
    ("Agenda Sent At", "DATE_TIME", ALL4,
     "A02 writes nothing today, so whether the agenda went out is unrecoverable after the fact."),
    ("Scope Agreed At", "DATE_TIME", OPP,
     "What was actually promised before the deliverable clock starts."),
    ("Proposal Sent At", "DATE_TIME", OPP, "Negotiation: the engagement letter went out."),
    ("Terms Agreed At", "DATE_TIME", OPP, "Negotiation: redlines settled."),
    ("Signature Sent At", "DATE_TIME", OPP, "Negotiation: out for signature. Drives L8."),
    ("Contract Signed At", "DATE_TIME", OPP, "Negotiation: countersigned. The only true Won."),
    ("Contact Verified At", "DATE_TIME", ["sellOpportunity"],
     "A working address before the cadence burns six touches against a bounced mailbox."),
    ("NDA Sent At", "DATE_TIME", ["fulfillment"], "Drives L8 on this board."),
    ("VDR Opened At", "DATE_TIME", ["fulfillment"], "Start of the longest stage on the board."),
    ("Offer Expected By", "DATE_TIME", ["fulfillment"],
     "Their stated date. 'Waiting on Offer' currently means waiting with nothing recording for "
     "what, or until when."),
    ("Last Contacted At", "DATE_TIME", OPP,
     "A real date. The existing Last Contacted is TEXT holding phrases like '4 days ago' and "
     "cannot be filtered or sorted."),
    ("Days Since Contact", "NUMBER", OPP,
     "Drift, visible without opening a record. Fulfillment already has it."),
]

SELECT_OPTIONS = {
    "Next Owner": [
        {"value": "US", "label": "Us", "color": "orange", "position": 0},
        {"value": "THEM", "label": "Them", "color": "blue", "position": 1},
    ],
}


# ── Stages ──────────────────────────────────────────────────────────────────
def _value(name):
    """Stage label -> API value. Stable and derivable, so the map cannot drift from the labels."""
    return name.upper().replace(" ", "_").replace("/", "_").replace("-", "_")


STAGE_COLORS = ["gray", "blue", "purple", "turquoise", "sky", "orange", "yellow", "red", "green"]

# The last group of a UUID is HEX, so the per-side prefix char cannot just be the side's first
# letter: `b` (buy) and `f` (fulfillment) happen to be hex digits, `s` (sell) is not. The original
# `side[:1]` therefore built eight malformed ids for sell only, and the server rejected the whole
# batch with METADATA_VALIDATION_FAILED / "Option id is invalid" — after buy and other had already
# been written. A dry run cannot catch this: it never POSTs, so nothing validates the ids.
# `buy` keeps `b` because those ids are already live in the CRM.
SIDE_HEX = {"buy": "b", "sell": "a", "fulfillment": "f"}


def stages_for(side):
    """The target stage option set for a pipeline, straight off the spec."""
    return [{"id": f"40404040-0000-4000-8000-{SIDE_HEX[side]}{i:011d}",
             "value": _value(name), "label": name,
             "color": STAGE_COLORS[i % len(STAGE_COLORS)], "position": i}
            for i, (name, _note, _new) in enumerate(ps.PIPELINES[side]["stages"])]


# How today's records land on the new stages. `None` means the rule is conditional and
# 04_map_stages resolves it per record — those are the two splits, and they are the only places
# this migration reads a record's data rather than just its stage.
STAGE_MAP = {
    "buy": {
        "NEW_LEAD": None,            # outreachSentAt empty -> LEAD, set -> QUALIFIED
        "MEETING_1": "INTRO_MEETING",
        "STRATEGY": "STRATEGY",
        "MEETING_2": "STRATEGY_REVIEW",
        "REVAMPS": "REVAMPS",
        "MEETING_3": "PITCH",
        "COMPLETED": "CLOSED",
        "SKIPPED": "CLOSED",
    },
    "sell": {
        "NEW_LEAD": None,            # no outreach -> TARGET, sent -> CONTACTED, replied -> ENGAGED
        "MEETING_1": "INTRO_MEETING",
        "STRATEGY": "STRATEGY",
        "MEETING_2": "STRATEGY_REVIEW",
        "REVAMPS": "REVAMPS",
        "MEETING_3": "PITCH",
        "CLOSED_WON": "CLOSED",
    },
    # The live values, confirmed by introspection — NOT derived from the labels. `Reached Out /
    # Teaser` is stored as REACHED_OUT and `Due Diligence` as DUE_DILIGENCE_VDR, so deriving
    # these from the label silently mapped nothing and left all 348 records where they were.
    "fulfillment": {
        "REACHED_OUT": None,         # repliedAt set -> ENGAGED, else APPROACH
        "MEETING_1": "MEETING_1",
        "NDA": "NDA",
        "MEETING_2": "MEETING_2",
        "DUE_DILIGENCE_VDR": "DUE_DILIGENCE",
        "MEETING_3": "MEETING_3",
        "WAITING_ON_OFFER": "OFFER_EXPECTED",
    },
}


def split_rule(side, record):
    """Resolve the conditional stage for the one record class that needs it."""
    if side == "buy":
        return "QUALIFIED" if record.get("outreachSentAt") else "LEAD"
    if side == "sell":
        if record.get("repliedAt"):
            return "ENGAGED"
        return "CONTACTED" if record.get("outreachSentAt") else "TARGET"
    return "ENGAGED" if record.get("repliedAt") else "APPROACH"


# ── Verdicts ────────────────────────────────────────────────────────────────
# Buy already has seven; Sell and Other have three. Do Not Contact is new everywhere and is the
# one status here with a consequence outside the CRM — see 03_verdicts.py.
VERDICTS = [
    ("CLOSED_WON", "Closed Won", "green"),
    ("CLOSED_LOST", "Closed Lost", "red"),
    ("NO_DECISION_MADE", "No Decision Made", "gray"),
    ("NOT_INTERESTED", "Not Interested", "orange"),
    ("DISQUALIFIED", "Disqualified", "gray"),
    ("DO_NOT_CONTACT", "Do Not Contact", "red"),
    ("FOLLOW_UP_90", "Follow Up (90)", "blue"),
    ("FOLLOW_UP_180", "Follow Up (180)", "purple"),
]
VERDICT_OBJECTS = OPP


def summary():
    lines = [f"{len(NEW_FIELDS)} new fields across {len(ALL4)} objects"]
    for side in ("buy", "sell", "fulfillment"):
        st = stages_for(side)
        lines.append(f"  {side:12} {len(st)} stages: " + " · ".join(s["label"] for s in st))
    lines.append(f"  verdicts     {len(VERDICTS)} options on {', '.join(VERDICT_OBJECTS)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
