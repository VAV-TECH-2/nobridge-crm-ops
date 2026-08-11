#!/usr/bin/env python3
"""Phase 0 probe: does REST PATCH round-trip every field type the autopilot writes?

Scratch file (leading underscore = not part of any pipeline; see README's Directory Guide).

Creates a throwaway record, PATCHes one field of each type, reads it back, then hard-deletes it.
The record is created with NO companyId on purpose: clienttype-sync's load_companies() only selects
rows `WHERE "companyId" IS NOT NULL` (sync.py:104), so a company-less record is invisible to it and
cannot trigger a spurious tag or move while this runs.

    python3 _probe_patch.py            # probe `other` (5 real records) and `fulfillment`
    python3 _probe_patch.py --keep     # leave the record behind for inspection
"""
import json
import sys

import crm
import twclient as tw

KEEP = "--keep" in sys.argv

# side -> [(field, value we send, what we expect back)] one per distinct Postgres type.
CASES = {
    "other": [
        ("stage", "QUALIFIED", "QUALIFIED"),                       # SELECT / enum
        ("stageChangedAt", "2026-08-10T04:05:06.000Z", None),       # DATE_TIME / timestamptz
        ("qualified", True, True),                                  # BOOLEAN
        ("daysSinceContact", 7, 7),                                 # NUMBER / double precision
        ("lastContacted", "7 days ago", "7 days ago"),               # TEXT
        ("nextOwner", "US", "US"),                                   # SELECT
        ("finalDecision", "FOLLOW_UP_90", "FOLLOW_UP_90"),           # SELECT
        ("nextSteps", "probe: where we last left off", None),        # TEXT
    ],
    "fulfillment": [
        ("stage", "NDA", "NDA"),
        ("followUpDate", "2026-08-20", None),                        # DATE (date, not timestamptz)
        ("lastContact", "2026-08-09", None),                         # DATE
        ("outcome", "PASSED", "PASSED"),                             # SELECT
        ("qualified", False, False),                                 # BOOLEAN
        ("daysSinceContact", 3.0, 3.0),                              # NUMBER
        ("nextActionDue", "2026-08-12T09:00:00.000Z", None),         # DATE_TIME
    ],
}

_CREATE = {
    "other": 'mutation{ createOtherOpportunity(data:{name:"zz-autopilot-probe", stage:LEAD}){ id } }',
    "fulfillment": 'mutation{ createFulfillment(data:{name:"zz-autopilot-probe", stage:APPROACH}){ id } }',
}
_DELETE = {
    "other": 'mutation D($id: UUID!){ destroyOtherOpportunity(id:$id){ id } }',
    "fulfillment": 'mutation D($id: UUID!){ destroyFulfillment(id:$id){ id } }',
}


def probe(side):
    print("\n=== %s ===" % side)
    data = tw.gql_checked(_CREATE[side])
    rid = list(data.values())[0]["id"]
    print("created %s" % rid)
    ok = bad = 0
    try:
        for field, send, expect in CASES[side]:
            try:
                crm.patch(side, rid, {field: send})
            except Exception as e:  # noqa: BLE001
                print("  FAIL  %-18s PATCH rejected: %s" % (field, str(e)[:200]))
                bad += 1
                continue
            got = crm.get_record(side, rid).get(field)
            if expect is not None and got != expect:
                print("  FAIL  %-18s sent %r got %r" % (field, send, got))
                bad += 1
            else:
                print("  ok    %-18s sent %-32r read back %r" % (field, send, got))
                ok += 1
    finally:
        if KEEP:
            print("kept %s (--keep)" % rid)
        else:
            tw.gql_checked(_DELETE[side], {"id": rid})
            print("destroyed %s" % rid)
    return ok, bad


if __name__ == "__main__":
    print("host:", tw.host())
    total_ok = total_bad = 0
    for side in CASES:
        o, b = probe(side)
        total_ok += o
        total_bad += b
    print("\n%d ok, %d failed" % (total_ok, total_bad))
    sys.exit(1 if total_bad else 0)
