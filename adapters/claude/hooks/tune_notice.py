#!/usr/bin/env python3
"""Claude Code SessionStart hook: when the /insights data is old (AGE_DAYS) or many sessions piled up since the
last report (NEW_SESSIONS), tells the user in one line that `tune-setup` can re-tune coach, context_notice,
ticket-flow and grillme. Informational only: it runs nothing and edits nothing. At most once a day."""
import datetime, glob, json, os, sys, tempfile, time

AGE_DAYS = 30
NEW_SESSIONS = 20
USAGE_DIR = os.path.expanduser("~/.claude/usage-data")


def due(usage_dir, now):
    """Reason string if a re-tune is due, else None. `now` is a unix time."""
    reports = glob.glob(os.path.join(usage_dir, "report*.html"))
    metas = glob.glob(os.path.join(usage_dir, "session-meta", "*.json"))
    if not reports:
        return "there is no /insights report yet" if len(metas) >= NEW_SESSIONS else None
    last = max(os.path.getmtime(p) for p in reports)
    days = int((now - last) // 86400)
    new = sum(1 for p in metas if os.path.getmtime(p) > last)
    if days >= AGE_DAYS:
        return f"the last /insights report is {days} days old"
    if new >= NEW_SESSIONS:
        return f"{new} sessions since the last /insights report"
    return None


def notice(usage_dir=USAGE_DIR, now=None, state_dir=None):
    try:
        now = time.time() if now is None else now
        reason = due(usage_dir, now)
        if not reason:
            return None
        day = datetime.date.fromtimestamp(now).isoformat()
        state = os.path.join(state_dir or tempfile.gettempdir(), "claude-tune-notice")
        try:
            with open(state) as f:
                if f.read() == day:
                    return None
        except OSError:
            pass
        with open(state, "w") as f:
            f.write(day)
        return (f"Setup tuning is due ({reason}). Say `tune-setup` and I propose changes to coach, context notice, "
                "ticket-flow and grillme; nothing is edited without your OK.")
    except Exception:  # a notice must never get in the way of the session
        return None


def main():
    json.load(sys.stdin)
    message = notice()
    if message:
        print(json.dumps({
            "systemMessage": message,
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"{message} Tell the user this in one short line in your first reply, then continue normally.",
            },
        }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
