#!/usr/bin/env python3
"""Claude Code PreToolUse hook: translates the event for core/guard/guard.py, which holds the policy logic.
Runs in every permission mode, bypass included. Installed as a symlink, so it finds core/ in the repo."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))


def reply(decision, reason):
    if decision != "allow":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}))


def main():
    import guard
    event = json.load(sys.stdin)
    tool = event.get("tool_name", "")
    if tool == "Bash":
        given = event.get("tool_input", {})
        ask = {"tool": "bash", "command": given.get("command", ""), "cwd": event.get("cwd"),
               "unsandboxed": given.get("dangerouslyDisableSandbox") is True}
    elif tool.startswith("mcp__"):
        _, server, name = tool.split("__", 2)
        ask = {"tool": "mcp", "name": f"{server}.{name}"}
    else:
        return
    reply(*guard.decide(ask, log=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a broken guard must not silently allow: ask instead
        reply("ask", f"policy guard failed ({exc}); confirm manually")
