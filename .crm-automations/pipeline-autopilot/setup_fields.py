#!/usr/bin/env python3
"""Add the five fields the workflow spec writes to but the CRM does not have. Additive only.

    python3 setup_fields.py            # dry run: what would be created, what already exists
    python3 setup_fields.py --apply    # execute

Idempotent — a field that already exists by name is reported and skipped, so a half-finished run is
resumed by running it again. Nothing existing is ever modified; this only ever calls createOneField.
Modelled on .crm-migrate-v2/01_add_fields.py, which did exactly this 45 times on 2026-08-09.

WHY these five, and not others: preflight.py compares every field the spec's steps claim to write
against the live columns. These five were the whole of the gap. Four are on fulfillment, which is
the largest board (348 records) and the one the spec describes least accurately today:

  meetingOutcome   9 steps write it (F07, F12/F14, F22, F32/F34, F42, F52/F54). Its absence is
                   called out in the spec's own F07 note: "Meeting Outcome does not exist on this
                   board today, so a fulfillment no-show has no state and no recovery." Adding it
                   is what makes L4 (no-show recovery) possible here at all.
  outreachSentAt   F03 writes it, and it is L12's anchor. Without it the approach cadence - the
                   loop that every one of the 348 records starts on - cannot be timed.
  recapSentAt      F15/F35/F55 write it after each meeting.
  owner            F02 "Assign an owner". Fulfillment has had no owner concept until now, which is
                   why "nobody owns it" has been the normal state rather than an exception.

  screeningNotes   B03/S03 "Screen it" write it, on buy/sell/other. Deliberately NOT on fulfillment:
                   F06 qualifies without writing screening notes, and a column nothing writes is
                   the exact drift the preflight exists to catch (which is also why the spec's
                   `Source` clause is being removed rather than turned into a field).

The relation is the only non-trivial one. It mirrors buy's `owner` exactly: MANY_TO_ONE onto
workspaceMember, onDelete SET_NULL, with an inverse collection on the member. `ownedFulfillments` is
free there - the member already carries buySideOpportunities / sellSideOpportunities /
otherOpportunities / ownedOpportunities, and this completes the set.
"""
import json
import sys

import crm
import twclient as tw

APPLY = "--apply" in sys.argv

CREATE = ("mutation C($input: CreateOneFieldMetadataInput!){"
          " createOneField(input:$input){ id name } }")

# Copied verbatim from buyOpportunity.meetingOutcome so the two boards agree on value, label,
# colour and order. Option ids are omitted on purpose - Twenty mints them.
MEETING_OUTCOME_OPTIONS = [
    {"value": "SCHEDULED", "label": "Scheduled", "color": "blue", "position": 0},
    {"value": "HOSTED", "label": "Hosted", "color": "green", "position": 1},
    {"value": "NO_SHOW", "label": "No-show", "color": "red", "position": 2},
    {"value": "RESCHEDULED", "label": "Rescheduled", "color": "orange", "position": 3},
    {"value": "CANCELLED", "label": "Cancelled", "color": "gray", "position": 4},
]

# (side, apiName, label, type, description, extra payload)
NEW_FIELDS = [
    ("fulfillment", "meetingOutcome", "Meeting Outcome", "SELECT",
     "What happened to the scheduled meeting. Drives L4 no-show recovery.",
     {"options": MEETING_OUTCOME_OPTIONS}),
    ("fulfillment", "outreachSentAt", "Outreach Sent At", "DATE_TIME",
     "When the teaser went out. The anchor L12's approach cadence counts from.", {}),
    ("fulfillment", "recapSentAt", "Recap Sent At", "DATE_TIME",
     "When the post-meeting recap went out.", {}),
    ("fulfillment", "owner", "Owner", "RELATION",
     "Fulfillments tied to the Workspace Member",
     {"relation": {"target": "workspaceMember", "inverse_label": "Owned Fulfillments",
                   "inverse_name": "ownedFulfillments"}}),
    ("buy", "screeningNotes", "Screening Notes", "TEXT",
     "Why this lead was qualified or disqualified.", {}),
    ("sell", "screeningNotes", "Screening Notes", "TEXT",
     "Why this lead was qualified or disqualified.", {}),
    ("other", "screeningNotes", "Screening Notes", "TEXT",
     "Why this lead was qualified or disqualified.", {}),
]


def main():
    ids = crm.object_ids()
    created, skipped, failed = [], [], []

    for side, name, label, ftype, note, extra in NEW_FIELDS:
        obj = crm.BOARDS[side]["object"]
        oid = ids.get(obj)
        if not oid:
            raise SystemExit("object %r not found in metadata" % obj)
        live = crm.fields(side)
        if name in live:
            skipped.append("%-12s %-16s exists (%s)" % (side, name, live[name]["type"]))
            continue

        payload = {"name": name, "label": label, "type": ftype,
                   "objectMetadataId": oid, "description": note, "isNullable": True}
        if "options" in extra:
            payload["options"] = extra["options"]
        if "relation" in extra:
            rel = extra["relation"]
            tid = ids.get(rel["target"])
            if not tid:
                raise SystemExit("relation target %r not found" % rel["target"])
            payload["relationCreationPayload"] = {
                "targetObjectMetadataId": tid,
                "targetFieldLabel": rel["inverse_label"],
                "targetFieldIcon": "IconUsers",
                "type": "MANY_TO_ONE",
            }
            payload["settings"] = {"onDelete": "SET_NULL", "relationType": "MANY_TO_ONE",
                                   "joinColumnName": name + "Id"}

        if not APPLY:
            created.append("%-12s %-16s %-10s WOULD CREATE" % (side, name, ftype))
            continue

        st, r = tw.meta(CREATE, {"input": {"field": payload}})
        if st == 200 and not r.get("errors") and "_error" not in r:
            created.append("%-12s %-16s %-10s created %s"
                           % (side, name, ftype, r["data"]["createOneField"]["id"]))
        else:
            failed.append("%-12s %-16s %s" % (side, name, json.dumps(r)[:400]))

    for line in skipped:
        print("  skip    " + line)
    for line in created:
        print("  create  " + line)
    for line in failed:
        print("  FAIL    " + line)

    print("\n%d to create, %d already present, %d failed%s"
          % (len(created), len(skipped), len(failed), "" if APPLY else "   (dry run)"))
    if not APPLY and created:
        print("Re-run with --apply to execute.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
