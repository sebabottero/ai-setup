#!/usr/bin/env python3
"""Claude Code PostToolUse / PostToolUseFailure / SessionEnd / SessionStart hook: records how a guard ask ended in
actions.log (core/guard/outcomes.py holds the logic and the limits). Never blocks, never prints.
  PostToolUse          the asked tool ran: `approved`
  PostToolUseFailure   it ran and failed: `approved`, unless the error says the permission was refused or the user interrupted
  SessionEnd           asks still unanswered: `declined` (inferred: the tool never ran)
  SessionStart         sweep of asks left by a session that died without SessionEnd: `declined`"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))

REFUSED = re.compile(r"(?i)(user|you) (rejected|denied|declined|doesn.t want)|permission.{0,40}denied|was (denied|rejected)")


def main():
    import outcomes
    event = json.load(sys.stdin)
    kind, session = event.get("hook_event_name"), event.get("session_id")
    if kind == "PostToolUse" and event.get("tool_use_id"):
        outcomes.resolve(event["tool_use_id"], "approved")
    elif kind == "PostToolUseFailure" and event.get("tool_use_id"):
        if not event.get("is_interrupt") and not REFUSED.search(str(event.get("error", ""))):
            outcomes.resolve(event["tool_use_id"], "approved")
    elif kind == "SessionEnd" and session:
        outcomes.resolve_session(session)
    elif kind == "SessionStart":
        outcomes.sweep(session)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # informational: a broken log must never get in the way of the session
