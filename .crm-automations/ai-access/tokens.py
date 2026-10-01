"""Issue, list, revoke and rotate AI Access tokens.

    python3 tokens.py --list
    python3 tokens.py --issue vilca@nobridge.co --scope write --label "Claude desktop"
    python3 tokens.py --issue fadil@nobridge.co --scope read --boards buy,fulfillment
    python3 tokens.py --revoke 3
    python3 tokens.py --rotate 3

A token is printed ONCE, at issue. Only its sha256 is kept, so there is no command that shows it
again and the dashboard cannot either — that is the point, not a limitation. Lost it? `--rotate`.

Issuing checks the email against the live CRM first. A token for somebody who is not an Admin or
Manager would be refused on every request anyway, and finding that out at issue time is cheaper
than finding it out from a 404 in a chat window.
"""
import argparse
import datetime
import sys

import deps  # noqa: F401
import auth
import crm
import store_ai

BASE = "https://app.nobridge.co/ai/mcp/"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _issue(args):
    email = args.issue.strip().lower()
    scope = args.scope
    boards = None
    if args.boards:
        boards = [b.strip() for b in args.boards.split(",") if b.strip()]
        bad = [b for b in boards if b not in crm.BOARDS]
        if bad:
            sys.exit("unknown board(s): %s (have: %s)" % (", ".join(bad), ", ".join(crm.BOARDS)))
        boards = ",".join(boards)

    if email in auth.ALLOW_EMAILS:
        role = "Admin (allowlist)"
    else:
        role = auth.crm_role_for_email(email)
        if not role:
            sys.exit("%s holds no role in the CRM (or the metadata API could not be read).\n"
                     "Invite them to the CRM first, or set AI_ACCESS_ALLOW_EMAILS to bootstrap."
                     % email)
        if role.strip().lower() not in auth.ALLOWED_ROLES:
            sys.exit("%s is %s in the CRM; this connector is for %s only. Refusing to issue a "
                     "token that every request would reject." % (email, role,
                                                                 " or ".join(auth.ALLOWED_ROLES)))
    member = crm.resolve_member(email)
    if not member:
        print("warning: %s does not resolve to a workspace member, so writes cannot be attributed "
              "to them." % email, file=sys.stderr)

    tid, secret = store_ai.create_token(email, scope, _now(), label=args.label, boards=boards,
                                        created_by=args.by)
    print("token #%d issued for %s (%s, scope=%s%s)"
          % (tid, email, role, scope, ", boards=" + boards if boards else ""))
    print()
    print("  Claude connector URL   %s%s" % (BASE, secret))
    print("  ChatGPT / API bearer   %s" % secret)
    print()
    print("This is the only time it is shown. Treat the URL as a password: anyone holding it has")
    print("%s's access to the CRM until the token is revoked." % email)


def _list(_args):
    rows = store_ai.all_tokens()
    if not rows:
        print("no tokens issued")
        return
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    counts = store_ai.request_counts(since)
    print("%-3s %-28s %-6s %-14s %-19s %-19s %6s  %s"
          % ("id", "email", "scope", "boards", "created", "last used", "7d", "label"))
    for r in rows:
        print("%-3s %-28s %-6s %-14s %-19s %-19s %6s  %s%s"
              % (r["id"], r["email"], r["scope"], r["boards"] or "all",
                 (r["created_at"] or "")[:19], (r["last_used_at"] or "—")[:19],
                 counts.get(r["id"], 0), r["label"] or "",
                 "   REVOKED " + (r["revoked_at"] or "")[:19] if r["revoked_at"] else ""))


def _revoke(args):
    row = store_ai.token_row(args.revoke)
    if not row:
        sys.exit("no token #%s" % args.revoke)
    if row["revoked_at"]:
        sys.exit("token #%s was already revoked %s" % (args.revoke, row["revoked_at"]))
    store_ai.revoke_token(args.revoke, _now())
    print("token #%s (%s) revoked. Any connector still holding it now gets a 404."
          % (args.revoke, row["email"]))


def _rotate(args):
    row = store_ai.token_row(args.rotate)
    if not row:
        sys.exit("no token #%s" % args.rotate)
    store_ai.revoke_token(args.rotate, _now())
    tid, secret = store_ai.create_token(
        row["email"], row["scope"], _now(),
        label=(row["label"] or "") + " (rotated)", boards=row["boards"], created_by=args.by)
    print("token #%s revoked, #%d issued for %s" % (args.rotate, tid, row["email"]))
    print()
    print("  Claude connector URL   %s%s" % (BASE, secret))
    print("  ChatGPT / API bearer   %s" % secret)


def main():
    ap = argparse.ArgumentParser(description="AI Access tokens")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--issue", metavar="EMAIL")
    g.add_argument("--revoke", metavar="ID", type=int)
    g.add_argument("--rotate", metavar="ID", type=int)
    ap.add_argument("--scope", choices=("read", "write"), default="read")
    ap.add_argument("--boards", help="restrict to these sides, e.g. buy,fulfillment")
    ap.add_argument("--label", help="what this token is for, e.g. 'Claude desktop'")
    ap.add_argument("--by", help="who issued it")
    args = ap.parse_args()

    if args.list:
        return _list(args)
    if args.issue:
        return _issue(args)
    if args.revoke:
        return _revoke(args)
    if args.rotate:
        return _rotate(args)


if __name__ == "__main__":
    main()
