"""Who is allowed in, and as whom.

Three gates in order, and each one is deliberate:

  1. the token          sha256 compared against every active row with hmac.compare_digest and NO
                        early exit, so response timing cannot leak which prefix matched. This is the
                        pattern the retired ops connector used (Sales Engine VM/src/server/mcp/
                        auth.ts) and it is worth keeping. An unknown token gets a bare 404 — never a
                        401, never a message — because a 401 confirms the endpoint exists.
  2. the CRM role       the token's email must STILL resolve to an Admin or Manager in the live CRM.
                        Revoking somebody in the CRM therefore revokes their connector, with no
                        second list to remember. Same check the ops dashboard does at sign-in.
  3. the identity       the email is resolved to a workspaceMember id, so every write this service
                        makes is attributed to a person rather than to "the automation".

The role query is ~25 lines duplicated from dashboard.py's `crm_role_for_email()`. That is on
purpose and cannot be avoided: the dashboard lives in the PRIVATE nobridge-ops-dashboard repo and
this file lives in the PUBLIC nobridge-crm-ops repo, so importing across is not an option. If the
role names change, both change.

Scope is per token: `read` or `write`, plus an optional board restriction. A read token that asks
for a write tool is refused by name, so the refusal reads as "this token cannot do that" rather
than as a mysterious validation failure.
"""
import hmac
import os
import time

import deps  # noqa: F401  — puts the autopilot modules on sys.path
import crm
import store_ai
import twclient as tw

# Roles the CRM must report for a login to be allowed. Same default as the dashboard.
ALLOWED_ROLES = [r.strip().lower() for r in
                 os.environ.get("AI_ACCESS_ROLES", "Admin,Manager").split(",") if r.strip()]
# Bootstrap bypass, for issuing the first token before anybody is a Manager. Same shape as the
# dashboard's FULL_ACCESS_EMAILS.
ALLOW_EMAILS = {e.strip().lower() for e in
                os.environ.get("AI_ACCESS_ALLOW_EMAILS", "").split(",") if e.strip()}

ROLE_TTL = int(os.environ.get("AI_ACCESS_ROLE_TTL", "600"))     # seconds

_ROLES_Q = ("query GetRoles { getRoles { id label workspaceMembers { id userEmail } } }")

_role_cache = {}      # email -> (expires_at, role|None)


class Denied(Exception):
    """Refused at a gate. `visible` False means answer 404 and say nothing."""

    def __init__(self, reason, visible=True):
        super().__init__(reason)
        self.reason = reason
        self.visible = visible


def crm_role_for_email(email):
    """The label of the CRM role this email holds, or None. Cached for ROLE_TTL.

    Errors are not cached: a metadata hiccup must not lock somebody out for ten minutes, and it must
    not let them in either — the caller treats None as denied.
    """
    key = (email or "").strip().lower()
    if not key:
        return None
    hit = _role_cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    try:
        data = tw.gql_checked(_ROLES_Q, metadata=True)
    except Exception:                        # noqa: BLE001 — fail closed, do not cache
        return None
    role = None
    for r in (data.get("getRoles") or []):
        for m in (r.get("workspaceMembers") or []):
            if (m.get("userEmail") or "").strip().lower() == key:
                role = r.get("label")
                break
        if role:
            break
    _role_cache[key] = (time.time() + ROLE_TTL, role)
    return role


def _match_token(secret):
    """The token row this secret belongs to, or None. Constant-time, no early exit."""
    if not secret:
        return None
    want = store_ai.hash_token(secret)
    found = None
    for row in store_ai.active_tokens():
        # compare_digest on every row, and keep going after a hit, so timing is flat.
        if hmac.compare_digest(row["token_sha256"], want):
            found = row
    return found


def principal(secret):
    """Verify a token end to end. Returns a principal dict, or raises Denied.

    {token_id, email, name, scope, boards, role, member_id}
    """
    row = _match_token(secret)
    if not row:
        # Invisible on purpose: the caller answers a bare 404.
        raise Denied("unknown token", visible=False)

    email = row["email"]
    if email in ALLOW_EMAILS:
        role = "Admin (allowlist)"
    else:
        role = crm_role_for_email(email)
        if not role:
            raise Denied("%s has no role in the CRM, or the role could not be read" % email)
        if role.strip().lower() not in ALLOWED_ROLES:
            raise Denied("%s is %s in the CRM; this connector is for %s only"
                         % (email, role, " or ".join(ALLOWED_ROLES)))

    member_id = crm.resolve_member(email)
    name = None
    for m in crm.workspace_members():
        if m["id"] == member_id:
            name = m["name"]
            break

    boards = None
    if row.get("boards"):
        boards = [b.strip() for b in row["boards"].split(",") if b.strip()]
        unknown = [b for b in boards if b not in crm.BOARDS]
        if unknown:
            raise Denied("token %s is scoped to unknown board(s): %s"
                         % (row["id"], ", ".join(unknown)))

    return {
        "token_id": row["id"],
        "label": row.get("label"),
        "email": email,
        "name": name,
        "scope": (row.get("scope") or "read").strip().lower(),
        "boards": boards,
        "role": role,
        "member_id": member_id,
    }


def may_write(p):
    return p.get("scope") == "write"


def check_board(p, side):
    """Raise Denied when a board-scoped token reaches for a board it does not hold."""
    if p.get("boards") and side not in p["boards"]:
        raise Denied("this token is scoped to %s and cannot touch %s"
                     % (", ".join(p["boards"]), side))


def bearer(header):
    """The token out of an Authorization header, or None."""
    if not header:
        return None
    parts = str(header).split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        try:
            print(principal(sys.argv[1]))
        except Denied as e:
            print("DENIED:", e.reason, "(visible)" if e.visible else "(404)")
    else:
        print("roles allowed:", ", ".join(ALLOWED_ROLES))
        print("allowlist:", ", ".join(sorted(ALLOW_EMAILS)) or "(none)")
        print("active tokens:", len(store_ai.active_tokens()))
