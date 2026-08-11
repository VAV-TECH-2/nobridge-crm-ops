"""Call any tool from a terminal, with no client and no token.

    python3 cli.py --list
    python3 cli.py find_record '{"query": "acme"}'
    python3 cli.py get_deal '{"company": "Acme"}'
    python3 cli.py whats_next '{"owner": "fadil"}'
    python3 cli.py crm_context '{"section": "gotchas"}'

This is the harness the read tools were built against, and the fastest way to see what a tool
actually returns before wondering why a model misread it. It bypasses auth on purpose — it runs as
whoever is at the keyboard, which on a laptop already means somebody holding the SSH key. WRITE
tools still refuse without `"confirm": true`, exactly as they do over the wire, and there is no flag
here to skip that.
"""
import json
import sys

import deps  # noqa: F401
import tools


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if sys.argv[1] == "--list":
        for t in tools.TOOLS:
            print("%-18s %s%s" % (t["name"], "" if t["readonly"] else "[write] ",
                                  t["description"].splitlines()[0].strip()))
        return 0

    name = sys.argv[1]
    t = tools.by_name(name)
    if not t:
        print("no such tool: %s (try --list)" % name, file=sys.stderr)
        return 2
    try:
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    except json.JSONDecodeError as e:
        print("arguments must be one JSON object: %s" % e, file=sys.stderr)
        return 2

    # A CLI principal: full scope, attributed to whoever is at the keyboard.
    p = {"token_id": None, "email": "cli@local", "name": "CLI", "scope": "write",
         "boards": None, "role": "CLI", "member_id": None}
    try:
        out = t["run"](args, p)
    except tools.ToolError as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    if isinstance(out, str):
        sys.stdout.write(out if out.endswith("\n") else out + "\n")
    else:
        print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
