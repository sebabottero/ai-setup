#!/usr/bin/env python3
"""Claude Code PreToolUse hook: records every rclone command that changes Google Drive (remote GDrive:) in a log
outside any work repo, so the task receipt can list them. Never blocks: it only logs and, for risky ones, warns.
Read-only subcommands (lsd, ls, lsf, about, check...) are not logged. It logs the intent before the command runs."""
import datetime, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))

REMOTE = "GDrive:"
SOURCE_ONLY = {"copy", "copyto", "sync"}  # these change the destination only; a download from Drive is not a change
BOTH_SIDES = {"move", "moveto", "bisync"}  # move deletes at the source, bisync writes on both sides
SINGLE = {"delete", "deletefile", "purge", "rmdir", "rmdirs", "mkdir", "touch", "cleanup"}
HIGH_RISK = {"sync", "purge"}
LOG = "~/Dev/logs/drive-changes.log"


def log_path():
    return os.path.expanduser(os.environ.get("AI_SETUP_DRIVE_LOG") or LOG)


def changes(command):
    """One dict per rclone command that changes the Drive remote: sub, src, dst, risks, dry."""
    import guard
    found = []
    for seg in guard.segments(command):
        words = seg.split()
        if not words or os.path.basename(words[0]) != "rclone":
            continue
        rest = words[1:]
        positional = [w for w in rest if not w.startswith("-")]
        if not positional:
            continue
        sub, args = positional[0], positional[1:]
        if sub in SOURCE_ONLY:
            hit = bool(args) and args[-1].startswith(REMOTE)
        elif sub in BOTH_SIDES or sub in SINGLE:
            hit = any(a.startswith(REMOTE) for a in args)
        else:
            continue
        if not hit:
            continue
        risks = []
        if sub in HIGH_RISK:
            risks.append(sub)
        no_trash = "--drive-use-trash=false" in rest or (
            "--drive-use-trash" in rest and rest[rest.index("--drive-use-trash") + 1:][:1] == ["false"])
        if no_trash:
            risks.append("--drive-use-trash=false")
        found.append({"sub": sub, "src": args[0] if args else "-", "dst": args[1] if len(args) > 1 else "-",
                      "risks": risks, "dry": "--dry-run" in rest or "-n" in rest})
    return found


def record(items, session="?"):
    path = log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for c in items:
                f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"), session, c["sub"], c["src"], c["dst"],
                                   "HIGH-RISK:" + ",".join(c["risks"]) if c["risks"] else "-",
                                   "dry-run" if c["dry"] else "-"]) + "\n")
    except OSError:
        pass  # a log that cannot be written must not get in the way of the command


def warning(items):
    risky = [c for c in items if c["risks"]]
    if not risky:
        return None
    what = "; ".join(f"rclone {c['sub']} {c['src']} ({', '.join(c['risks'])})" for c in risky)
    return f"HIGH RISK Drive change: {what}. Make sure the user approved it and list it in the receipt."


def main():
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Bash":
        return
    items = changes(event.get("tool_input", {}).get("command", ""))
    if not items:
        return
    record(items, event.get("session_id", "?"))
    what = "; ".join(f"rclone {c['sub']} {c['src']} {c['dst']}".rstrip(" -") for c in items)
    message = warning(items) or f"Drive change logged: {what}. List it in the receipt Drive line."
    print(json.dumps({"systemMessage": message, "hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
