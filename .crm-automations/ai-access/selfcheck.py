"""Refuse to run on anything that would make this connector lie.

Same idea as the autopilot's preflight.py, and for the same reason: the connector's whole value is
that it describes the CRM as it actually is. A stale spec, a section that will not render, a tool
schema a client will reject — each turns confident answers into confident nonsense, and each is
cheap to catch here.

    python3 selfcheck.py          human-readable, exit 1 on any blocker
    python3 selfcheck.py --json   for the dashboard tab

Blockers stop a deploy. Warnings are worth reading.
"""
import json
import sys

import deps  # noqa: F401
import context
import crm
import openapi
import spec
import store_ai
import tools

# JSON Schema types a client will actually accept in a tool definition.
_TYPES = {"object", "string", "integer", "number", "boolean", "array", "null"}


def check():
    rep = {"spec": spec.spec_path(), "spec_sha": spec.spec_sha(),
           "autopilot": deps.autopilot_dir(),
           "context_fingerprint": None, "tools": len(tools.TOOLS),
           "blockers": [], "warnings": [], "sections": {}}
    B = rep["blockers"].append
    W = rep["warnings"].append

    # ── the tool registry ──
    names = [t["name"] for t in tools.TOOLS]
    for n in set(names):
        if names.count(n) > 1:
            B("two tools are both called %r; a client would see only one of them" % n)
    for t in tools.TOOLS:
        s = t["input_schema"]
        if s.get("type") != "object":
            B("%s: input schema must be an object" % t["name"])
        for field, sub in (s.get("properties") or {}).items():
            ty = sub.get("type")
            if ty not in _TYPES:
                B("%s.%s has type %r, which is not a JSON Schema type" % (t["name"], field, ty))
            if not sub.get("description") and field != "confirm":
                W("%s.%s has no description, so a model has to guess what it means"
                  % (t["name"], field))
        for req in s.get("required") or []:
            if req not in (s.get("properties") or {}):
                B("%s requires %r, which is not in its properties" % (t["name"], req))
        if not t["description"].strip():
            B("%s has no description; ChatGPT will never call it" % t["name"])
        if t["writes"] and not t["confirm"]:
            B("%s writes but has no confirm gate" % t["name"])
        if t["writes"] and t["readonly"]:
            B("%s is marked both readonly and writing" % t["name"])

    # ── the two renderings agree ──
    doc = openapi.document()
    if len(doc["paths"]) != len(tools.TOOLS):
        B("OpenAPI has %d operations for %d tools" % (len(doc["paths"]), len(tools.TOOLS)))
    if len(doc["paths"]) > openapi.MAX_OPERATIONS:
        B("%d operations exceeds ChatGPT's limit of %d — the GPT will not import"
          % (len(doc["paths"]), openapi.MAX_OPERATIONS))
    for t in tools.TOOLS:
        if ("/ai/tools/" + t["name"]) not in doc["paths"]:
            B("%s is missing from the OpenAPI document" % t["name"])
    mcp = {m["name"] for m in _mcp_names()}
    if mcp != set(names):
        B("the MCP tool list and the registry disagree: %s" % (mcp ^ set(names)))

    # ── the context pack renders, all of it ──
    for key, _desc in context.sections():
        try:
            body = context.render(key)
        except Exception as e:                      # noqa: BLE001
            B("context section %s failed to render: %s: %s" % (key, type(e).__name__, e))
            continue
        rep["sections"][key] = len(body)
        if len(body) < 200:
            W("context section %s rendered only %d characters" % (key, len(body)))
        if body.startswith("Unknown section"):
            B("context section %s is in the index but render() does not know it" % key)
    try:
        rep["context_fingerprint"] = context.fingerprint()
    except Exception as e:                          # noqa: BLE001
        B("could not fingerprint the context: %s" % e)

    # ── the two prompt renderings ──
    try:
        gpt = context.gpt_instructions(tools.tool_lines())
        rep["gpt_chars"] = len(gpt)
        if len(gpt) > context.GPT_CAP:
            B("the ChatGPT instruction block is %d characters; the Custom GPT box truncates at "
              "8000 and our cap is %d" % (len(gpt), context.GPT_CAP))
        elif len(gpt) > context.GPT_CAP * 0.9:
            W("the ChatGPT instruction block is %d characters, close to the %d cap"
              % (len(gpt), context.GPT_CAP))
    except Exception as e:                          # noqa: BLE001
        B("could not build the ChatGPT instructions: %s" % e)
    try:
        rep["mcp_instruction_chars"] = len(context.instructions(tools.tool_lines()))
    except Exception as e:                          # noqa: BLE001
        B("could not build the MCP instructions: %s" % e)

    # ── the live CRM agrees with the spec about stages ──
    # Not a re-run of preflight.py — that owns spec-vs-CRM drift. This is the narrower question the
    # connector depends on: can it name a stage a client asked for?
    for side, board in crm.BOARDS.items():
        pipe = board["pipeline"]
        if not pipe:
            continue
        try:
            live = set(crm.stage_options(side))
        except Exception as e:                      # noqa: BLE001
            B("could not read %s's stages: %s" % (side, e))
            continue
        missing = [s for s in spec.stage_enums(pipe) if s not in live]
        if missing:
            B("%s: the spec names stage(s) %s that the CRM does not have — run the autopilot's "
              "preflight.py, and deploy the spec if it is stale" % (side, ", ".join(missing)))

    # ── tokens ──
    active = store_ai.active_tokens()
    rep["tokens_active"] = len(active)
    if not active:
        W("no tokens are issued, so nothing can connect yet — tokens.py --issue <email>")
    for t in active:
        if t["boards"]:
            unknown = [b for b in t["boards"].split(",") if b.strip() not in crm.BOARDS]
            if unknown:
                B("token #%s is scoped to unknown board(s) %s and would fail every request"
                  % (t["id"], ", ".join(unknown)))
    return rep


def _mcp_names():
    import server
    return server.mcp_tools()


def main():
    as_json = "--json" in sys.argv
    rep = check()
    if as_json:
        print(json.dumps(rep, indent=2, default=str))
        return 1 if rep["blockers"] else 0

    print("spec:      %s" % rep["spec"])
    print("sha256:    %s" % rep["spec_sha"][:16])
    print("autopilot: %s" % rep["autopilot"])
    print("tools:     %d (%d write)" % (rep["tools"],
                                        sum(1 for t in tools.TOOLS if t["writes"])))
    print("context:   %s · %d sections · %d chars total"
          % (rep["context_fingerprint"], len(rep["sections"]), sum(rep["sections"].values())))
    print("prompts:   MCP %d chars · ChatGPT %d/%d chars"
          % (rep.get("mcp_instruction_chars", 0), rep.get("gpt_chars", 0), context.GPT_CAP))
    print("tokens:    %d active" % rep.get("tokens_active", 0))
    print()
    for w in rep["warnings"]:
        print("warn  %s" % w)
    for b in rep["blockers"]:
        print("BLOCK %s" % b)
    print()
    print("%d blocker(s), %d warning(s)" % (len(rep["blockers"]), len(rep["warnings"])))
    return 1 if rep["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
