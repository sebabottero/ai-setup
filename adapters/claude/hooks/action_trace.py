#!/usr/bin/env python3
"""Claude Code PreToolUse hook: records the shell commands that a policy `trace` rule matches, in a log outside any
work repo, so the task receipt can list them. Never blocks: it only logs and, for risky ones, warns. No rules: no-op.

Rule (in any layer's policy.json, merged by the layers):
  "trace": [{"match": ["tool sub * remote:*", "tool sub remote:*"], "log": "{{DEV}}/logs/x.log",
             "high_risk": {"purge": ["tool purge *"], "--flag=false": ["* --flag=false", "* --flag=false *"]}}]
  match      globs over one simple command: the program (path dropped) and its words that are not flags, so a flag
             between the subcommand and the path does not matter. List the subcommands that change something
             (an allowlist); anything else is not logged. Any hit logs it.
  high_risk  optional {label: [globs]}; a glob is tried on the non-flag text and on the whole text. A hit marks the line HIGH-RISK:<label>.
  log        file the lines go to; {{DEV}} is the layers' dev_root
It logs the intent before the command runs. Line: time, session, sub, src, dst, HIGH-RISK:<hits> or -, dry-run or -."""
import datetime, fnmatch, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))


def load_policy():
    """The composed policy. AI_SETUP_POLICY points at another file (tests)."""
    import guard
    given = os.environ.get("AI_SETUP_POLICY")
    if given:
        with open(given) as f:
            return json.load(f)
    return guard.load()


def rules(policy):
    """The well-formed trace rules of a policy; anything else is ignored."""
    found = policy.get("trace") if isinstance(policy, dict) else None
    if not isinstance(found, list):
        return []
    out = []
    for r in found:
        if isinstance(r, dict) and isinstance(r.get("log"), str) and isinstance(r.get("match"), list) and r["match"]:
            out.append(r)
    return out


def log_path(rule, policy):
    import layers
    return os.path.expanduser(rule["log"].replace("{{DEV}}", layers.dev_root(policy)))


def _hit(texts, globs):
    return any(isinstance(g, str) and fnmatch.fnmatchcase(t, g) for g in globs or [] for t in texts)


def _risk_labels(rule, texts):
    risk = rule.get("high_risk")
    if isinstance(risk, list):  # a plain list: each glob is its own label
        risk = {g: [g] for g in risk if isinstance(g, str)}
    if not isinstance(risk, dict):
        return []
    return [label for label, globs in risk.items() if isinstance(globs, list) and _hit(texts, globs)]


def changes(command, rule_list):
    """One dict per matching command: sub, src, dst, risks, dry, rule, text."""
    import guard
    found = []
    for seg in guard.segments(command):
        words = seg.split()
        if not words:
            continue
        program = os.path.basename(words[0])  # /opt/homebrew/bin/x -> x
        rest = words[1:]
        positional = [w for w in rest if not w.startswith("-")]
        plain = " ".join([program] + positional)
        whole = " ".join([program] + rest)
        for rule in rule_list:
            if not _hit([plain], rule["match"]):
                continue
            found.append({"sub": positional[0] if positional else "-", "src": positional[1] if len(positional) > 1 else "-",
                          "dst": positional[2] if len(positional) > 2 else "-", "risks": _risk_labels(rule, [plain, whole]),
                          "dry": "--dry-run" in rest or "-n" in rest, "rule": rule, "text": whole})
            break  # one line per command, however many rules match
    return found


def record(items, policy, session="?"):
    for c in items:
        path = log_path(c["rule"], policy)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"), session, c["sub"], c["src"], c["dst"],
                                   "HIGH-RISK:" + ",".join(c["risks"]) if c["risks"] else "-",
                                   "dry-run" if c["dry"] else "-"]) + "\n")
        except OSError:
            pass  # a log that cannot be written must not get in the way of the command


def warning(items):
    risky = [c for c in items if c["risks"]]
    if not risky:
        return None
    what = "; ".join(f"{c['text']} ({', '.join(c['risks'])})" for c in risky)
    return f"HIGH RISK change: {what}. Make sure the user approved it and list it in the receipt."


def main():
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Bash":
        return
    policy = load_policy()
    rule_list = rules(policy)
    if not rule_list:
        return
    items = changes(event.get("tool_input", {}).get("command", ""), rule_list)
    if not items:
        return
    record(items, policy, event.get("session_id", "?"))
    what = "; ".join(" ".join([c["text"].split()[0], c["sub"], c["src"], c["dst"]]).rstrip(" -") for c in items)
    message = warning(items) or f"Change logged: {what}. List it in the receipt."
    print(json.dumps({"systemMessage": message, "hookSpecificOutput": {
        "hookEventName": "PreToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
