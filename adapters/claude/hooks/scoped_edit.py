#!/usr/bin/env python3
"""Claude Code PreToolUse / PostToolUse hook for Edit | Write | MultiEdit | NotebookEdit: scoped approvals for protected paths
inside a ticket worktree (core/guard/scope.py holds the logic and the rules). Installed as a symlink, so it finds core/ in the repo.
  PreToolUse    `ask` or `allow` for a protected path in a ticket worktree; nothing printed for any other path
  PostToolUse   the tool ran: the ask this hook raised for the scope's exact path becomes a grant (never blocks, never prints)
A broken hook asks instead of allowing; a hook that does not run at all (uninstalled, crashed interpreter) leaves the normal
pipeline in charge, see docs/DESIGN.md entry 6."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))


def reply(decision, reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}))


def main(kind):
    import scope
    event = json.loads(sys.stdin.read())
    kind[0] = event.get("hook_event_name")
    if kind[0] == "PostToolUse":
        scope.after(event)
        return
    result = scope.check(event)
    if result:
        import guard
        guard.log_decision("edit", result[0], "scoped-edit")  # the same guard.log line as a Bash decision: usage_report counts it
        reply(*result)


if __name__ == "__main__":
    kind = [None]
    try:
        main(kind)
    except Exception as exc:  # a broken hook must not silently allow: ask instead (a failed grant only means one more ask)
        if kind[0] != "PostToolUse":
            reply("ask", f"scoped-edit hook failed ({exc}); confirm manually")
