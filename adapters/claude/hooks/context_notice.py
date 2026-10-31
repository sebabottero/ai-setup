#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: tells the user, in one line, when the session context is getting big.
Informational only: it never blocks. Warns above START tokens and again every STEP tokens after that."""
import json, os, sys, tempfile

TAIL_BYTES = 256 * 1024


def _env_int(name, default):
    try:
        value = int(os.environ.get(name, ""))
        return value if value > 0 else default
    except ValueError:
        return default


def thresholds():
    """START and STEP, overridable with CLAUDE_CONTEXT_NOTICE_START / _STEP (invalid values fall back)."""
    return _env_int("CLAUDE_CONTEXT_NOTICE_START", 150_000), _env_int("CLAUDE_CONTEXT_NOTICE_STEP", 50_000)


def _scan(lines):
    last = 0
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        usage = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
        if usage:
            last = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return last


def last_context(path):
    """Tokens in the context of the last assistant turn (input + cache read + cache creation).
    Reads only the tail of the transcript; falls back to the whole file if the tail has no usage."""
    with open(path, "rb") as f:
        size = f.seek(0, os.SEEK_END)
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            lines = f.read().decode(errors="ignore").splitlines()[1:]  # first line is partial
            last = _scan(lines)
            if last:
                return last
        f.seek(0)
        return _scan(f.read().decode(errors="ignore").splitlines())


def notice(path, session, state_dir=None):
    try:
        start, step = thresholds()
        tokens = last_context(path)
        state = os.path.join(state_dir or tempfile.gettempdir(), f"claude-context-notice-{session}")
        if tokens < start:
            try:
                os.remove(state)  # e.g. after /compact: let the notice fire again on the next climb
            except OSError:
                pass
            return None
        band = (tokens - start) // step
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
                "say `handoff` and I write it, then /clear.")
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
