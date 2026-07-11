"""Detect duplicate fulfillment records (read-only).

Flags two duplicate shapes on the `_fulfillment` board:
  1. same company (companyId) with >1 active fulfillment record, and
  2. same suffix-normalized name across >1 record (catches mislinked / duplicate company rows,
     e.g. "Bina San Prima, PT" vs "PT. BINA SAN PRIMA").

Read-only: prints a report, writes nothing. Run: python detect_dupes.py
Reuses the same normalization as import_kmp / .crm-migrate so the keys line up.
"""
import sys, json
sys.path.insert(0, ".crm-fulfillment")
import tw

SUFFIX = {"inc","llc","ltd","limited","co","company","group","corp","corporation","holding",
          "holdings","pte","plc","sa","llp","partners","the","tbk","pt","berhad","bhd",
          "sdn","persero"}
import re
def norm_name(s):
    if not s: return ""
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return " ".join(t for t in s.split() if t and t not in SUFFIX)

def fetch_all(plural, node_fields):
    q = "query($after:String){ %s(first:60, after:$after){ edges{ node{ %s } } pageInfo{ hasNextPage endCursor } } }" % (plural, node_fields)
    after, acc = None, []
    while True:
        st, r = tw.gql(q, {"after": after})
        if st != 200 or "data" not in r:
            raise RuntimeError("fetch %s failed: %s %s" % (plural, st, json.dumps(r)[:300]))
        conn = r["data"][plural]
        acc += [e["node"] for e in conn["edges"]]
        if not conn["pageInfo"]["hasNextPage"]: break
        after = conn["pageInfo"]["endCursor"]
    return acc

def main():
    fuls = fetch_all("fulfillments", "id name companyId mandate")
    by_company, by_name = {}, {}
    for f in fuls:
        if f.get("companyId"):
            by_company.setdefault(f["companyId"], []).append(f)
        k = norm_name(f.get("name") or "")
        if k:
            by_name.setdefault(k, []).append(f)

    dup_company = {c: rows for c, rows in by_company.items() if len(rows) > 1}
    dup_name = {k: rows for k, rows in by_name.items()
                if len({r["id"] for r in rows}) > 1
                and len({r.get("companyId") for r in rows}) > 1}  # only cross-company name dups

    print("=== %d fulfillment records scanned ===" % len(fuls))
    print("\n[1] SAME COMPANY with >1 fulfillment (%d):" % len(dup_company))
    for c, rows in dup_company.items():
        print("  company %s:" % c)
        for r in rows:
            print("     - %s  %s" % (r["id"], r.get("name")))
    print("\n[2] SAME NAME across different company records (%d):" % len(dup_name))
    for k, rows in dup_name.items():
        print("  '%s':" % k)
        for r in rows:
            print("     - %s  name=%r  company=%s" % (r["id"], r.get("name"), r.get("companyId")))
    total = len(dup_company) + len(dup_name)
    print("\n%s" % ("NO DUPLICATES FOUND." if total == 0 else "%d duplicate group(s) need review." % total))
    sys.exit(1 if total else 0)

if __name__ == "__main__":
    main()
