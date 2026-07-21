#!/usr/bin/env python3
"""
Bidirectional Company <-> opportunity-type sync (5 segments).
Company.clientType (MULTI_SELECT) is the authoritative segment tag.

Rules per company, each pass:
  A. Tag -> ensure opp (auto-create): for every tag with no opp in that object, create one.
  B. Opp -> ensure tag (auto-tag, additive): every object with an opp ensures its segment is in the tag set.
  C. Source-of-truth MOVE (only destructive case): an opp whose object's segment is not in the tag set is a mismatch.
       - if the company has EXACTLY ONE tag -> move the mismatched opp into that tagged object.
            * same opp-family (buy/sell/other) -> SQL same-id move (notes/tasks/timeline/attachments re-pointed).
            * cross-family (to/from fulfillment/networking) -> FLAG only (logged, never auto-transformed).
       - otherwise (0 or >=2 tags) -> ambiguous: add the opp's segment to the tag set (falls back to rule B).
  D. Delete -> untag (honor user deletes): a tag whose opp was soft-deleted within the last
     RECENT_DELETE_WINDOW_MIN minutes is treated as an intentional removal -> drop the tag
     instead of re-creating the opp (rule A). Quirk: re-tagging a company within the window
     of a delete gets undone; re-tag after the window and rule A re-creates as before.
  Never deletes a deal. Moves preserve the record id and re-point all morph links.

Flags: --dry  (print planned actions, write nothing)
Env:   MOVE_MODE=move|flag (default move) -- 'flag' turns rule-C same-family moves into log-only too.
       RECENT_DELETE_WINDOW_MIN (default 15) -- how far back a soft-delete counts for rule D.
"""
import os, sys, json, time, subprocess, urllib.request, urllib.error
from datetime import datetime, timezone

DRY = "--dry" in sys.argv
MOVE_MODE = os.environ.get("MOVE_MODE", "move").strip().lower()
RECENT_DELETE_WINDOW_MIN = int(os.environ.get("RECENT_DELETE_WINDOW_MIN", "15"))
ENV_PATH = "/home/azureuser/sales-engine/.env"
GQL = "http://127.0.0.1:3000/graphql"
SCH = "workspace_4cukon3ltvwq3m1goqws3p4lv"
LOG = "/home/azureuser/clienttype-sync.log"
DB = ["docker", "exec", "-i", "twenty-db-1", "psql", "-U", "postgres", "-d", "default"]

OPP_FAMILY = {"BUY_SIDE", "SELL_SIDE", "OTHERS"}
SEG = {
    "BUY_SIDE":    {"table": "_buyOpportunity",   "col": "targetBuyOpportunityId",   "create": "createBuyOpportunity",   "stage": "NEW_LEAD"},
    "SELL_SIDE":   {"table": "_sellOpportunity",  "col": "targetSellOpportunityId",  "create": "createSellOpportunity",  "stage": "NEW_LEAD"},
    "OTHERS":      {"table": "_otherOpportunity", "col": "targetOtherOpportunityId", "create": "createOtherOpportunity", "stage": "NEW_LEAD"},
    "FULFILLMENT": {"table": "_fulfillment",      "col": "targetFulfillmentId",      "create": "createFulfillment",      "stage": "REACHED_OUT"},
    "NETWORK":     {"table": "_networking",       "col": "targetNetworkingId",       "create": "createNetworking",       "stage": "REACHED_OUT"},
}
MORPH = ["attachment", "noteTarget", "taskTarget", "timelineActivity"]


def token():
    for line in open(ENV_PATH):
        if line.startswith("TWENTY_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("TWENTY_API_KEY not found in " + ENV_PATH)


TOKEN = token()


def psql(sql, stop_on_error=True):
    cmd = list(DB) + (["-v", "ON_ERROR_STOP=1"] if stop_on_error else []) + ["-tAq", "-c", sql]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("psql failed: " + (p.stderr or p.stdout))
    return p.stdout


def psql_json(inner):
    out = psql("SELECT COALESCE(json_agg(t), '[]'::json) FROM (" + inner + ") t;").strip()
    return json.loads(out) if out else []


THROTTLE = float(os.environ.get("GQL_THROTTLE", "0.7"))  # spacing between writes (~85/min, under the 100/min cap)


def gql(query, retries=8):
    for attempt in range(retries):
        time.sleep(THROTTLE)
        req = urllib.request.Request(GQL, data=json.dumps({"query": query}).encode(),
                                     headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        except urllib.error.HTTPError as e:
            r = json.loads(e.read().decode())
        if r.get("errors"):
            msg = json.dumps(r["errors"])
            if "LIMIT_REACHED" in msg and attempt < retries - 1:
                time.sleep(10)
                continue
            raise RuntimeError(msg)
        return r["data"]


def lit(s):
    return "'" + s.replace("'", "''") + "'"


def load_companies():
    union = " UNION ALL ".join(
        'SELECT "companyId" cid, %s seg, id oppid FROM "%s"."%s" WHERE "deletedAt" IS NULL AND "companyId" IS NOT NULL'
        % (lit(seg), SCH, m["table"]) for seg, m in SEG.items())
    # segments with a recent user-deleted opp (rule D): soft-deleted inside the window
    deleted_union = " UNION ALL ".join(
        'SELECT "companyId" cid, %s seg FROM "%s"."%s" WHERE "deletedAt" >= now() - interval \'%d minutes\' AND "companyId" IS NOT NULL'
        % (lit(seg), SCH, m["table"], RECENT_DELETE_WINDOW_MIN) for seg, m in SEG.items())
    inner = (
        "WITH opps AS (" + union + "), recent_del AS (" + deleted_union + ") "
        'SELECT c.id, c.name, COALESCE(c."clientType", \'{}\') AS tags, '
        "COALESCE((SELECT json_agg(json_build_object('seg', o.seg, 'oppid', o.oppid)) FROM opps o WHERE o.cid = c.id), '[]'::json) AS opps, "
        "COALESCE((SELECT json_agg(DISTINCT d.seg) FROM recent_del d WHERE d.cid = c.id), '[]'::json) AS recent_deleted "
        'FROM "' + SCH + '".company c WHERE c."deletedAt" IS NULL'
    )
    return psql_json(inner)


def create_opp(seg, cid, cname):
    m = SEG[seg]
    q = 'mutation { %s(data:{name:%s, stage:%s, companyId:%s}) { id } }' % (
        m["create"], json.dumps(cname or "(unnamed)"), m["stage"], json.dumps(cid))
    return gql(q)


def set_tags(cid, tags):
    arr = "[" + ",".join(sorted(tags)) + "]"
    gql('mutation { updateCompany(id:%s, data:{clientType:%s}) { id } }' % (json.dumps(cid), arr))


COLS_CACHE = {}


def cols_info(table):
    """[(name, data_type, udt_name)] for non-generated columns, in order."""
    if table not in COLS_CACHE:
        out = psql("SELECT column_name||'|'||data_type||'|'||udt_name FROM information_schema.columns "
                   "WHERE table_schema=%s AND table_name=%s AND is_generated='NEVER' ORDER BY ordinal_position;"
                   % (lit(SCH), lit(table)))
        COLS_CACHE[table] = [tuple(l.split("|", 2)) for l in out.splitlines() if l]
    return COLS_CACHE[table]


def sql_move(oppid, src_seg, tgt_seg):
    """Same-id move within the opp family. One transaction; re-points all morph links.
    Copies only columns common to both tables, casting per-table enum types through text."""
    src, tgt = SEG[src_seg]["table"], SEG[tgt_seg]["table"]
    tgt_udt = {n: udt for (n, dt, udt) in cols_info(tgt)}
    cols, exprs = [], []
    for n, dt, udt in cols_info(src):
        if n not in tgt_udt:
            continue  # tables differ (e.g. legacy engagementStatus) -> skip
        cols.append('"%s"' % n)
        tu = tgt_udt[n]
        if dt == "USER-DEFINED" and udt != tu:        # per-table scalar enum
            exprs.append('"%s"::text::"%s"."%s"' % (n, SCH, tu))
        elif dt == "ARRAY" and udt != tu:             # per-table enum array (defensive)
            exprs.append('"%s"::text[]::"%s"."%s"' % (n, SCH, tu))
        else:
            exprs.append('"%s"' % n)
    collist = ",".join(cols)
    sellist = ",".join(exprs)
    src_col, tgt_col = SEG[src_seg]["col"], SEG[tgt_seg]["col"]
    stmts = ["BEGIN;"]
    stmts.append('INSERT INTO "%s"."%s" (%s) SELECT %s FROM "%s"."%s" WHERE id=%s AND "deletedAt" IS NULL;'
                 % (SCH, tgt, collist, sellist, SCH, src, lit(oppid)))
    for t in MORPH:
        stmts.append('UPDATE "%s"."%s" SET "%s"=%s, "%s"=NULL WHERE "%s"=%s;'
                     % (SCH, t, tgt_col, lit(oppid), src_col, src_col, lit(oppid)))
    stmts.append('DELETE FROM "%s"."%s" WHERE id=%s;' % (SCH, src, lit(oppid)))
    stmts.append("COMMIT;")
    psql("\n".join(stmts))


def main():
    companies = load_companies()
    plan_create, plan_tag, plan_move, plan_flag, plan_untag = [], [], [], [], []

    for c in companies:
        cid, cname = c["id"], c["name"]
        tags = set(c["tags"] or [])
        by_seg = {}
        for o in c["opps"]:
            by_seg.setdefault(o["seg"], []).append(o["oppid"])
        opp_segs = set(by_seg)
        mismatch = opp_segs - tags

        present_after = set(opp_segs & tags)
        if len(tags) == 1 and mismatch:
            target = next(iter(tags))
            moved_any = False
            for seg in mismatch:
                for oppid in by_seg[seg]:
                    if seg in OPP_FAMILY and target in OPP_FAMILY and MOVE_MODE == "move":
                        plan_move.append((cid, cname, oppid, seg, target)); moved_any = True
                    else:
                        plan_flag.append((cid, cname, oppid, seg, target)); present_after.add(seg)
            if moved_any:
                present_after.add(target)
            final_tags = set(tags)
        else:
            final_tags = tags | opp_segs
            present_after = set(opp_segs)

        recent_deleted = set(c["recent_deleted"] or [])
        for t in list(final_tags):
            if t not in present_after:
                if t in recent_deleted:   # rule D: honor the delete, drop the tag
                    final_tags.discard(t)
                    plan_untag.append((cid, cname, t))
                else:
                    plan_create.append((cid, cname, t))
        if final_tags != tags:
            plan_tag.append((cid, cname, sorted(final_tags)))

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    head = "[%s] %s companies | create=%d tag=%d move=%d flag=%d untag=%d" % (
        ts, len(companies), len(plan_create), len(plan_tag), len(plan_move), len(plan_flag), len(plan_untag))
    print(head)
    for cid, cn, t in plan_create:
        print("  CREATE %-12s opp for %s (%s)" % (t, cn, cid))
    for cid, cn, t in plan_untag:
        print("  UNTAG  %-12s from %s - opp deleted by user (%s)" % (t, cn, cid))
    for cid, cn, t in plan_tag:
        print("  TAG    %s := %s (%s)" % (cn, t, cid))
    for cid, cn, oid, s, t in plan_move:
        print("  MOVE   %s opp %s  %s -> %s (%s)" % (cn, oid, s, t, cid))
    for cid, cn, oid, s, t in plan_flag:
        print("  FLAG   %s opp %s sits in %s, company tagged %s only - review (%s)" % (cn, oid, s, t, cid))

    if DRY:
        print("DRY RUN - no writes")
        return

    done_c = done_t = 0
    moved_ok = []
    errs = []
    for cid, cn, oid, s, t in plan_move:
        try:
            sql_move(oid, s, t); moved_ok.append((cid, cn, oid, s, t))
        except Exception as e:
            errs.append("move %s %s->%s: %s" % (oid, s, t, e))
    for cid, cn, t in plan_create:
        try:
            create_opp(t, cid, cn); done_c += 1
        except Exception as e:
            errs.append("create %s/%s: %s" % (cn, t, e))
    for cid, cn, t in plan_tag:
        try:
            set_tags(cid, t); done_t += 1
        except Exception as e:
            errs.append("tag %s: %s" % (cn, e))

    summ = "[%s] applied create=%d tag=%d move=%d flag=%d untag=%d errors=%d" % (
        ts, done_c, done_t, len(moved_ok), len(plan_flag), len(plan_untag), len(errs))
    print(summ)
    with open(LOG, "a") as f:
        f.write(summ + "\n")
        for e in errs:
            f.write("    ERR " + e + "\n")
        for cid, cn, oid, s, t in moved_ok:
            f.write("    MOVED %s opp %s %s->%s (%s)\n" % (cn, oid, s, t, cid))
        for cid, cn, oid, s, t in plan_flag:
            f.write("    FLAG %s opp %s in %s tagged %s (%s)\n" % (cn, oid, s, t, cid))
        for cid, cn, t in plan_untag:
            f.write("    UNTAG %s from %s - opp deleted by user (%s)\n" % (t, cn, cid))
    if errs:
        for e in errs:
            print("  ERR " + e)
        sys.exit(1)


if __name__ == "__main__":
    main()
