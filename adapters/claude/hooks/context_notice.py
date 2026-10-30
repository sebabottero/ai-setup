#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: tells the user, in one line, when the session context is getting big.
Informational only: it never blocks. Warns above START tokens and again every STEP tokens after that."""
import json, os, sys, tempfile

START = 150_000
STEP = 50_000


def last_context(path):
    """Tokens in the context of the last assistant turn (input + cache read + cache creation)."""
    last = 0
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            usage = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
            if usage:
                last = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return last


def notice(path, session, state_dir=None):
    try:
        tokens = last_context(path)
        if tokens < START:
            return None
        band = (tokens - START) // STEP
        state = os.path.join(state_dir or tempfile.gettempdir(), f"claude-context-notice-{session}")
        try:
            with open(state) as f:
                seen = int(f.read())
        except (OSError, ValueError):
            seen = -1
        if band <= seen:
            return None
        with open(state, "w") as f:
            f.write(str(band))
        return (f"Context is {tokens // 1000}k tokens. Long sessions cost more and answer worse: "
                "consider a handoff (session-handoff) and /clear.")
    except Exception:  # a notice must never get in the way of the prompt
        return None


def output(message):
    """systemMessage alone is not shown in the chat; additionalContext reaches the model, which relays it."""
    return {
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"{message} Start your next reply with one short line telling the user this, then continue normally.",
        },
    }


def main():
    event = json.load(sys.stdin)
    message = notice(event.get("transcript_path"), event.get("session_id", "unknown"))
    if message:
        print(json.dumps(output(message)))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
