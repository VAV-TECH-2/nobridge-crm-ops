"""Apply the email-derived enrichment to fulfillment records.

Reads out_*.json (subagent decisions) + enrich_bundles.json (for candidate email->personId
and current POC), then for each record updates only the NON-NULL fields:
  engagementStatus(progress), outcome, nextSteps, notes, and pointOfContactId (ONLY when the
  record currently has no POC and the suggested email matches a known person at the company).

  python apply_enrichment.py            # DRY RUN: print plan + counts
  python apply_enrichment.py --apply    # execute via updateFulfillment
"""
import os, sys, json, glob, tw

APPLY = "--apply" in sys.argv
SCRATCH = r"C:\Users\Vilca\AppData\Local\Temp\claude\C--Users-Vilca\1aed1a39-51ef-4b14-84ca-df422c32606a\scratchpad"

UPDATE = "mutation U($id: UUID!, $data: FulfillmentUpdateInput!){ updateFulfillment(id:$id, data:$data){ id } }"

VALID_PROGRESS = {"COMPLETE", "ACTIVELY_SPEAKING", "GHOSTED"}
VALID_OUTCOME = {"OFFER_RECEIVED", "PASSED", "DROPPED"}


def load_decisions():
    out = []
    for f in sorted(glob.glob(os.path.join(SCRATCH, "out_*.json"))):
        out += json.load(open(f, encoding="utf-8"))
    return out


def load_bundle_index():
    bundles = json.load(open(os.path.join(SCRATCH, "enrich_bundles.json"), encoding="utf-8"))
    idx = {}
    for b in bundles:
        emap = {}
        for c in (b.get("candidates") or []):
            if c.get("email") and c.get("personId"):
                emap[c["email"].lower()] = c["personId"]
        idx[b["id"]] = {"emailToPid": emap, "currentPocId": b.get("currentPocId")}
    return idx


def main():
    decisions = load_decisions()
    idx = load_bundle_index()
    print(f"MODE: {'APPLY' if APPLY else 'DRY RUN'} | decisions: {len(decisions)}")

    stats = {"progress": 0, "outcome": 0, "nextSteps": 0, "notes": 0, "poc_set": 0,
             "poc_suggested_but_exists": 0, "no_change": 0, "fail": 0}
    prog_counts, outc_counts = {}, {}

    for d in decisions:
        fid = d.get("id")
        if not fid or fid not in idx:
            continue
        data = {}
        if d.get("progress") in VALID_PROGRESS:
            data["engagementStatus"] = d["progress"]; stats["progress"] += 1
            prog_counts[d["progress"]] = prog_counts.get(d["progress"], 0) + 1
        if d.get("outcome") in VALID_OUTCOME:
            data["outcome"] = d["outcome"]; stats["outcome"] += 1
            outc_counts[d["outcome"]] = outc_counts.get(d["outcome"], 0) + 1
        if d.get("nextSteps"):
            data["nextSteps"] = d["nextSteps"][:500]; stats["nextSteps"] += 1
        if d.get("notes"):
            data["notes"] = d["notes"][:1000]; stats["notes"] += 1

        # point of contact: only fill when missing AND email maps to a person at the company
        email = (d.get("pointOfContactEmail") or "").lower().strip()
        if email:
            pid = idx[fid]["emailToPid"].get(email)
            if pid and not idx[fid]["currentPocId"]:
                data["pointOfContactId"] = pid; stats["poc_set"] += 1
            elif pid and idx[fid]["currentPocId"]:
                stats["poc_suggested_but_exists"] += 1

        if not data:
            stats["no_change"] += 1
            continue
        if not APPLY:
            continue
        st, r = tw.gql(UPDATE, {"id": fid, "data": data})
        if not (st == 200 and r.get("data", {}).get("updateFulfillment")):
            stats["fail"] += 1
            print("  !! FAIL", fid, st, json.dumps(r)[:200])

    print("progress set:", prog_counts)
    print("outcome set:", outc_counts)
    print("stats:", json.dumps(stats, indent=1))
    print("DONE." if APPLY else "DRY RUN — re-run with --apply.")


if __name__ == "__main__":
    main()
