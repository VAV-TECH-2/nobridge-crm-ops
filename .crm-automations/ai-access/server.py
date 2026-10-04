"""API Access (Contextualized) — formerly "AI Access". One process, two front doors.

    POST /ai/mcp/<token>        MCP over Streamable HTTP, for Claude. Token in the PATH, because a
                                custom connector cannot be told to send a header.
    POST /ai/tools/<name>       plain JSON, Authorization: Bearer <token>, for a ChatGPT Custom GPT.
    GET  /ai/openapi.json       the OpenAPI 3.1 document those Actions are built from. Public: it
                                contains no secrets, and ChatGPT fetches it unauthenticated.
    GET  /ai/gpt-instructions.txt   the block to paste into a hosted custom GPT. Token-gated.
    GET  /ai/agent-instructions.txt the system prompt for an agent that calls this over HTTP itself,
                                including the wire contract and every parameter. Token-gated.
    GET  /ai/context.md         the whole context pack, for reading or diffing. Token-gated.
    GET  /ai/status             what the dashboard's AI Access tab shows. Loopback only.
    GET  /healthz               liveness.

JSON-RPC is hand-rolled — no MCP SDK, no dependencies at all beyond the standard library, matching
the ops dashboard and the Finance connector (Nobridge Finance/app/mcp/[token]/route.ts, live since
2026-07-06 and the pattern this follows). Stateless: no sessions to lose when the unit restarts, so
GET (the SSE pull) and DELETE (session teardown) are 405.

TWO THINGS THAT LOOK WRONG AND ARE NOT:

  An unknown token gets a bare 404, not a 401. A 401 confirms the endpoint exists and invites
  guessing; a 404 is indistinguishable from a typo in the hostname.

  Every tool call runs under ONE lock. store.py keeps a single SQLite connection, twclient throttles
  through a module global and crm.py caches metadata in module state — none of that is thread-safe.
  Serialising also keeps this service inside Twenty's 100-request-per-60-second budget, which is per
  WORKSPACE and already shared with the autopilot timer, clienttype-sync and blocklist-guard. One
  person talking to a chat window does not need concurrency; a corrupted write would not be worth it.

OAUTH DISCOVERY. MCP clients probe /.well-known/oauth-* and /register before connecting, and if
those return HTML the client decides an OAuth server is there and fails trying to parse it. Caddy
answers them 404 for this host (deploy/Caddyfile.unified) — the same fix fin.nobridge.co
needed on 2026-07-28. This server also answers them 404 itself, so a direct-to-port test behaves the
same way as the proxied one.
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import deps  # noqa: F401
import auth
import context
import openapi
import store_ai
import tools

PORT = int(os.environ.get("AI_ACCESS_PORT", "3300"))
BIND = os.environ.get("AI_ACCESS_BIND", "127.0.0.1")

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "nobridge-crm", "title": "Nobridge API Access (Contextualized)",
               "version": "1.0.0"}
MAX_BODY = 1024 * 1024

# One lock for every tool call. See the module docstring.
_LOCK = threading.Lock()

_OAUTH_PROBE = re.compile(r"^/(\.well-known/(oauth|openid)[^/]*|register)$")


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ── the tool call, logged and locked ───────────────────────────────────────────────────────────

def run_tool(name, args, principal, client):
    """Execute one tool. Returns (ok, payload). Never raises — a failure is a result here."""
    t = tools.by_name(name)
    started = time.time()
    if not t:
        known = ", ".join(x["name"] for x in tools.TOOLS)
        payload = "No tool called %r. Available: %s." % (name, known)
        store_ai.log_request(_now(), principal.get("token_id"), principal.get("email"), client,
                             name, args, False, payload, 0)
        return False, payload

    # Scope is checked before the lock: a read token asking for a write tool should be told so by
    # name, not made to queue for it.
    if t["writes"] and not auth.may_write(principal):
        payload = ("This token is read-only, so `%s` is not available to it. Ask for a write-scoped "
                   "token (tokens.py --issue <email> --scope write) if you need to change records."
                   % name)
        store_ai.log_request(_now(), principal.get("token_id"), principal.get("email"), client,
                             name, args, False, payload, 0)
        return False, payload

    ok, payload, err = True, None, None
    try:
        with _LOCK:
            payload = t["run"](args or {}, principal)
    except tools.ToolError as e:
        ok, payload, err = False, str(e), str(e)
    except auth.Denied as e:
        ok, payload, err = False, e.reason, e.reason
    except Exception as e:                     # noqa: BLE001
        ok = False
        err = "%s: %s" % (type(e).__name__, e)
        payload = ("The CRM could not answer that: %s. This is a fault on our side, not something to "
                   "retry with different arguments." % err)
        print("[ai-access] %s failed: %s" % (name, err), file=sys.stderr)
        traceback.print_exc()

    ms = int((time.time() - started) * 1000)
    run_id = payload.get("run") if (ok and isinstance(payload, dict)) else None
    store_ai.log_request(_now(), principal.get("token_id"), principal.get("email"), client,
                         name, args, ok, err, ms, run_id)
    if principal.get("token_id"):
        store_ai.touch_token(principal["token_id"], _now())
    return ok, payload


def _as_text(payload):
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2, default=str)


# ── JSON-RPC ───────────────────────────────────────────────────────────────────────────────────

def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def mcp_tools():
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"],
             "annotations": {"readOnlyHint": t["readonly"],
                             "destructiveHint": False,
                             "title": t["name"].replace("_", " ").title()}}
            for t in tools.TOOLS]


def _resources():
    return [{"uri": "crm://context/" + key, "name": key, "title": key,
             "description": desc, "mimeType": "text/markdown"}
            for key, desc in context.sections()]


def dispatch(msg, principal):
    """One JSON-RPC message -> one reply, or None when no reply is due."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request")
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    # Notifications never get a reply, and neither does anything with no id.
    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    if method == "initialize":
        requested = params.get("protocolVersion")
        return _result(rid, {
            # Echo the client's version when it named one: the widest compatibility, and the same
            # thing the Finance connector does.
            "protocolVersion": requested if isinstance(requested, str) else PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"listChanged": False, "subscribe": False}},
            "serverInfo": SERVER_INFO,
            # This is the whole point of the context engine: orientation lands BEFORE the first call.
            "instructions": context.instructions(tools.tool_lines()),
        })

    if method == "ping":
        return _result(rid, {})

    if method == "tools/list":
        return _result(rid, {"tools": mcp_tools()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        ok, payload = run_tool(name, args, principal, "mcp")
        return _result(rid, {"content": [{"type": "text", "text": _as_text(payload)}],
                             "isError": not ok})

    if method == "resources/list":
        return _result(rid, {"resources": _resources()})

    if method == "resources/read":
        uri = params.get("uri") or ""
        key = uri.split("crm://context/", 1)[1] if uri.startswith("crm://context/") else None
        if not key:
            return _error(rid, -32602, "unknown resource %r" % uri)
        ok, payload = run_tool("crm_context", {"section": key}, principal, "mcp")
        return _result(rid, {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                           "text": _as_text(payload)}]})

    if method == "prompts/list":
        return _result(rid, {"prompts": []})

    if rid is None:
        return None
    return _error(rid, -32601, "Method not found: %s" % method)


# ── HTTP ───────────────────────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "nobridge-ai-access"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass                      # journald gets what we choose to print, not one line per request

    # ── plumbing ──
    def _send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str))

    def _404(self):
        # Deliberately bare: see the module docstring.
        self._send(404, "", "text/plain")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return None
        if n > MAX_BODY:
            return "TOO_LARGE"
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "BAD_JSON"

    def _principal(self, secret):
        """A verified principal, or None having already answered the request."""
        try:
            return auth.principal(secret)
        except auth.Denied as e:
            if e.visible:
                self._json(403, {"error": e.reason})
            else:
                self._404()
            return None

    def _loopback(self):
        return (self.client_address[0] or "").startswith("127.")

    # ── GET ──
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        try:
            if path == "/healthz":
                return self._json(200, {"ok": True, "service": "ai-access",
                                        "tools": len(tools.TOOLS)})

            # No OAuth here. Answering 404 is what makes an MCP client fall back to the token in the
            # URL instead of trying to register with a sign-in service that does not exist.
            if _OAUTH_PROBE.match(path):
                return self._404()

            if path == "/ai/openapi.json":
                return self._json(200, openapi.document())

            if path == "/ai/status":
                if not self._loopback():
                    return self._404()
                return self._json(200, status())

            # Token may arrive as a bearer header or as ?token= (so a browser can open it).
            secret = auth.bearer(self.headers.get("Authorization"))
            if not secret and query:
                for part in query.split("&"):
                    if part.startswith("token="):
                        secret = part.split("=", 1)[1]

            if path in ("/ai/gpt-instructions.txt", "/ai/agent-instructions.txt",
                        "/ai/context.md"):
                p = self._principal(secret)
                if not p:
                    return None
                if path.endswith("gpt-instructions.txt"):
                    return self._send(200, context.gpt_instructions(),
                                      "text/plain; charset=utf-8")
                if path.endswith("agent-instructions.txt"):
                    return self._send(200,
                                      context.agent_instructions(tools.tool_reference()),
                                      "text/plain; charset=utf-8")
                return self._send(200, context.full_markdown(), "text/markdown; charset=utf-8")

            m = re.match(r"^/ai/mcp/([A-Za-z0-9_\-]+)$", path)
            if m:
                # Stateless: there is no stream to open and no session to end.
                try:
                    auth.principal(m.group(1))
                except auth.Denied as e:
                    return self._404() if not e.visible else self._json(403, {"error": e.reason})
                self.send_response(405)
                self.send_header("Allow", "POST")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None

            return self._404()
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": str(e)[:300]})

    def do_DELETE(self):
        return self._404()

    # ── POST ──
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            m = re.match(r"^/ai/mcp/([A-Za-z0-9_\-]+)$", path)
            if m:
                return self._mcp(m.group(1))
            m = re.match(r"^/ai/tools/([a-z_]+)$", path)
            if m:
                return self._rest_tool(m.group(1))
            return self._404()
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return self._json(500, {"error": str(e)[:300]})

    def _mcp(self, secret):
        p = self._principal(secret)
        if not p:
            return None
        body = self._body()
        if body == "TOO_LARGE":
            return self._json(413, _error(None, -32600, "body too large"))
        if body == "BAD_JSON" or body is None:
            return self._json(400, _error(None, -32700, "parse error"))

        messages = body if isinstance(body, list) else [body]
        replies = [r for r in (dispatch(msg, p) for msg in messages) if r is not None]
        if not replies:
            # Notifications only. 202 with no body is what the spec asks for.
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return self._json(200, replies if isinstance(body, list) else replies[0])

    def _rest_tool(self, name):
        """The ChatGPT Actions door. Same tools, same guardrails, Bearer auth, plain JSON."""
        secret = auth.bearer(self.headers.get("Authorization"))
        p = self._principal(secret)
        if not p:
            return None
        body = self._body()
        if body == "TOO_LARGE":
            return self._json(413, {"error": "body too large"})
        if body == "BAD_JSON":
            return self._json(400, {"error": "body must be a JSON object"})
        args = body if isinstance(body, dict) else {}
        ok, payload = run_tool(name, args, p, "openapi")
        if not ok:
            # 200 with an explicit error, not a 4xx: a Custom GPT surfaces the body of a 200 to the
            # model and often swallows an error status, and the refusal text is the useful part.
            return self._json(200, {"ok": False, "error": _as_text(payload)})
        return self._json(200, {"ok": True,
                                "result": payload if not isinstance(payload, str) else None,
                                "text": payload if isinstance(payload, str) else None})


# ── status, for the dashboard tab ───────────────────────────────────────────────────────────────

def status():
    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    counts = store_ai.request_counts(since)
    toks = []
    for t in store_ai.all_tokens():
        toks.append({"id": t["id"], "label": t["label"], "email": t["email"], "scope": t["scope"],
                     "boards": t["boards"] or "all", "created_at": t["created_at"],
                     "last_used_at": t["last_used_at"], "requests_7d": counts.get(t["id"], 0),
                     "requests_total": t["requests"], "revoked_at": t["revoked_at"]})
    return {
        "service": "ai-access",
        "port": PORT,
        "tools": [{"name": t["name"], "writes": t["writes"]} for t in tools.TOOLS],
        "context_fingerprint": context.fingerprint(),
        # The ChatGPT block travels with the status so the dashboard has one loopback endpoint to
        # call rather than a second, differently-authenticated one. It is not a secret — it is the
        # same public description of the workflow WORKFLOWS.md carries.
        "gpt_instructions": context.gpt_instructions(),
        "agent_instructions": context.agent_instructions(tools.tool_reference()),
        "tokens": toks,
        "recent_requests": store_ai.recent_requests(40),
        "tool_counts_7d": store_ai.tool_counts(since),
    }


def main():
    # Fail fast and loudly if the rules or the CRM cannot be reached: a connector that answers
    # questions from a half-loaded spec is worse than one that is down.
    import spec as _spec
    print("[ai-access] spec %s (%s)" % (_spec.spec_path(), _spec.spec_sha()[:12]))
    print("[ai-access] %d tools, context %s" % (len(tools.TOOLS), context.fingerprint()))
    print("[ai-access] tokens: %d active" % len(store_ai.active_tokens()))
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print("[ai-access] listening on %s:%d" % (BIND, PORT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
