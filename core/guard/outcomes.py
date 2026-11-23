"""How a guard ask ended, for the action log (Claude Code only).

Claude Code does not tell a hook whether the user approved an ask. What it does give (verified against the 2.1.x binary):
the PreToolUse and PostToolUse payloads carry the same `tool_use_id`, a tool that ran fires PostToolUse (or
PostToolUseFailure when it failed), and SessionEnd / SessionStart carry `session_id`. So:
  * the guard writes a pending marker per asked tool_use_id (write_marker);
  * the tool ran -> `approved` (resolve), the marker is gone;
  * the session ends with the marker still there -> `declined` (resolve_session); a marker left by a crashed session is
    swept as `declined` at the next SessionStart once it is older than STALE seconds (sweep).
`declined` is inferred (the tool never ran), not reported by Claude Code. Each outcome is one more actions.log line with the
ask's session, risk, rule and command, and `approved` / `declined` in the "what" column. AI_SETUP_PENDING_DIR overrides
~/.ai-setup/pending ("off" disables)."""
import hashlib, json, os, re, time

STALE = 24 * 3600


def pending_dir():
    path = os.environ.get("AI_SETUP_PENDING_DIR") or os.path.expanduser("~/.ai-setup/pending")
    return None if path == "off" else path


def _file(tool_use_id):
    base = pending_dir()
    return os.path.join(base, re.sub(r"[^\w-]", "_", str(tool_use_id)) + ".json") if base else None


def write_marker(tool_use_id, session, risk, rule, text):
    path = _file(tool_use_id)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"session": session or "?", "risk": risk, "rule": rule, "text": text, "time": time.time()}, f)
    except OSError:
        pass  # a marker that cannot be written only loses the outcome line


def _take(path):
    """Read and remove a marker; None if it is gone or unreadable (another hook got it first)."""
    try:
        with open(path) as f:
            data = json.load(f)
        os.remove(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _record(data, outcome):
    import guard
    guard.write_action_line(data.get("session"), str(data.get("risk", "low")), outcome, str(data.get("rule", "-")),
                            str(data.get("text", "")))


def resolve(tool_use_id, outcome):
    """The asked tool ran (or not): write its outcome line once. No marker (not an ask): nothing."""
    path = _file(tool_use_id)
    data = _take(path) if path and os.path.exists(path) else None
    if data:
        _record(data, outcome)


def _markers():
    base = pending_dir()
    try:
        names = sorted(os.listdir(base)) if base else []
    except OSError:
        return
    for name in names:
        if name.endswith(".json"):
            yield os.path.join(base, name)


def resolve_session(session, outcome="declined"):
    """SessionEnd: every marker of this session is still unanswered."""
    for path in _markers():
        try:
            with open(path) as f:
                mine = json.load(f).get("session") == session
        except (OSError, ValueError, AttributeError):
            continue
        data = _take(path) if mine else None
        if data:
            _record(data, outcome)


def sweep(current_session, outcome="declined", now=None):
    """SessionStart: markers of other sessions older than STALE belong to a session that died without SessionEnd."""
    now = time.time() if now is None else now
    for path in _markers():
        try:
            with open(path) as f:
                data = json.load(f)
            stale = data.get("session") != current_session and now - float(data.get("time", now)) > STALE
        except (OSError, ValueError, AttributeError, TypeError):
            continue
        data = _take(path) if stale else None
        if data:
            _record(data, outcome)


def sessions_dir():
    path = os.environ.get("AI_SETUP_SESSIONS_DIR") or os.path.expanduser("~/.ai-setup/sessions")
    return None if path == "off" else path


def _session_file(cwd):
    base = sessions_dir()
    if not base or not cwd:
        return None
    return os.path.join(base, hashlib.sha1(os.path.realpath(cwd).encode()).hexdigest()[:16])


def remember_session(cwd, session):
    """SessionStart: the session id of the newest session that started in this folder, for run_json.py --session auto."""
    path = _session_file(cwd)
    if not path or not session:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(session))
    except OSError:
        pass


def current_session(cwd):
    """The id remember_session stored for this folder, or None."""
    path = _session_file(cwd)
    try:
        with open(path) as f:
            return f.read().strip() or None
    except (OSError, TypeError):
        return None
