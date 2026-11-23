#!/usr/bin/env python3
"""Claude Code PostToolUse / PostToolUseFailure / SessionEnd / SessionStart hook: records how a guard ask ended in
actions.log (core/guard/outcomes.py holds the logic and the limits). Never blocks, never prints.
  PostToolUse          the asked tool ran: `approved`
  PostToolUseFailure   it ran and failed: `approved`, unless the error says the permission was refused or the user interrupted
  SessionEnd           asks still unanswered: `declined` (inferred: the tool never ran)
  SessionStart         remembers the session id of this folder (run_json.py --session auto); sweep of asks left by a session that died without SessionEnd: `declined`"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))

# The harness's own refusal texts (Claude Code 2.1.317), anchored at the start so shell output such as
# "bash: ./x.sh: Permission denied" inside a command's error does not count.
REFUSED = re.compile(r"\s*(The user doesn.t want to proceed with this tool use|Permission to use .{0,300}? has been denied"
                     r"|Permission for this tool use was denied)")


def main():
    import outcomes
    event = json.load(sys.stdin)
    kind, session = event.get("hook_event_name"), event.get("session_id")
    if kind == "PostToolUse" and event.get("tool_use_id"):
        outcomes.resolve(event["tool_use_id"], "approved")
    elif kind == "PostToolUseFailure" and event.get("tool_use_id"):
        if not event.get("is_interrupt") and not REFUSED.match(str(event.get("error", ""))):
            outcomes.resolve(event["tool_use_id"], "approved")
    elif kind == "SessionEnd" and session:
        outcomes.resolve_session(session)
    elif kind == "SessionStart":
        outcomes.remember_session(event.get("cwd"), session)
        outcomes.sweep(session)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # informational: a broken log must never get in the way of the session
