#!/usr/bin/env python3
"""Local usage report from Claude Code transcripts: how many sessions grow past 150k tokens, which models
run the turns, which tools dominate. Reads ~/.claude/projects only; sends nothing anywhere.
Usage: python3 -I adapters/claude/usage_report.py [days]   (default: all transcripts)
       python3 -I adapters/claude/usage_report.py --ticket <slug> [--dev-root DIR]
           tokens, turns and wall time of the sessions listed in <dev root>/handoffs/<slug>/run.json"""
import argparse, collections, datetime, glob, json, os, sys, time

LIMIT = 150_000
TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def summarize(paths):
    models, tools = collections.Counter(), collections.Counter()
    contexts, output, total_in = [], 0, 0
    for path in paths:
        peak = 0
        with open(path, errors="ignore") as f:
            lines = f.readlines()
        for line in lines:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue
            usage = msg.get("usage")
            if usage and d.get("type") == "assistant":
                used = sum(usage.get(k, 0) for k in TOKEN_KEYS)
                peak = max(peak, used)
                total_in += used
                output += usage.get("output_tokens", 0)
                models[msg.get("model", "?")] += 1
            for block in msg.get("content") if isinstance(msg.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
        if peak:
            contexts.append(peak)
    return {"sessions": len(contexts), "over_150k": sum(c > LIMIT for c in contexts),
            "over_300k": sum(c > 2 * LIMIT for c in contexts), "max_context": max(contexts, default=0),
            "output_tokens": output, "input_tokens": total_in, "turns": sum(models.values()), "models": models, "tools": tools}


def guard_summary(path=None, since=None):
    """Counts from the guard log (time, tool, decision, rule per line), from `since` (a datetime) on; None if there is no log yet."""
    path = path or os.environ.get("AI_SETUP_GUARD_LOG") or os.path.expanduser("~/.ai-setup/guard.log")
    counts, rules = collections.Counter(), collections.Counter()
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 4 and parts[2] in ("allow", "ask", "deny") and (since is None or (
                        _when(parts[0]) or datetime.datetime.min) >= since):
                    counts[parts[2]] += 1
                    if parts[2] != "allow":
                        rules[parts[3]] += 1
    except OSError:
        return None
    return {"allow": counts["allow"], "ask": counts["ask"], "deny": counts["deny"], "rules": rules}


def _guard_log_path():
    return os.environ.get("AI_SETUP_GUARD_LOG") or os.path.expanduser("~/.ai-setup/guard.log")


def _when(text):
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def guard_decisions(path=None, since=None):
    """[(time, decision, rule)] from the guard log, from `since` on; None if there is no log."""
    path = path or _guard_log_path()
    out = []
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                when = _when(parts[0]) if len(parts) == 4 else None
                if when and parts[2] in ("allow", "ask", "deny") and (since is None or when >= since):
                    out.append((when, parts[2], parts[3]))
    except OSError:
        return None
    return out


def _actions_path():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core", "guard"))
    import guard
    return guard.actions_log_path()


def ask_outcomes(path=None, since=None, until=None):
    """How the asks in the action log ended (guard.actions_log_path unless a path is given). Outcome lines are linked to
    the `asked` line by session + command, oldest first; the ask's own time is the decision time (a `declined` line is
    stamped when it was inferred). Returns None without a log, else {approved, declined, unknown, unresolved, asks}.
    Old lines without outcomes count as unresolved."""
    path = path or _actions_path()
    asks, outcomes = collections.defaultdict(list), collections.defaultdict(collections.deque)
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 6:
                    continue
                when = _when(parts[0])
                key = (parts[1], parts[5])
                if parts[3] == "asked" and when:
                    asks[key].append(when)
                elif parts[3] in ("approved", "declined", "unknown"):
                    outcomes[key].append(parts[3])
    except OSError:
        return None
    result = collections.Counter()
    for key, times in asks.items():
        for when in sorted(times):
            outcome = outcomes[key].popleft() if outcomes[key] else None  # oldest ask takes the oldest outcome
            if (since is not None and when < since) or (until is not None and when >= until):
                continue
            result["asks"] += 1
            result[outcome or "unresolved"] += 1
    return {k: result[k] for k in ("asks", "approved", "declined", "unknown", "unresolved")}


def ask_report(days=None, now=None, guard_path=None, actions_path=None):
    """Lines about ask fatigue: asks per day, ask rate per ISO week, approval rate, top 5 ask rules."""
    now = now or datetime.datetime.now()
    since = now - datetime.timedelta(days=days) if days else None
    decisions = guard_decisions(guard_path, since)
    lines = []
    if decisions is None:
        lines.append(f"Asks: no guard log yet ({_guard_log_path()} is written when the guard runs)")
    else:
        asks = [d for d in decisions if d[1] == "ask"]
        per_day = collections.Counter(d[0].date().isoformat() for d in asks)
        days_seen = sorted(per_day)
        lines.append(f"Asks per day ({len(asks)} in {len(days_seen)} days with asks"
                     + (f", avg {len(asks) / len(days_seen):.1f}" if days_seen else "") + "): "
                     + (", ".join(f"{d[5:]} {per_day[d]}" for d in days_seen[-7:]) or "none")
                     + (" (last 7 shown)" if len(days_seen) > 7 else ""))
        week_all, week_ask = collections.Counter(), collections.Counter()
        for when, decision, _ in decisions:
            iso = when.isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"
            week_all[week] += 1
            week_ask[week] += decision == "ask"
        lines.append("Ask rate per week (asks / guard decisions): " + (", ".join(
            f"{w} {100 * week_ask[w] / week_all[w]:.0f}% ({week_ask[w]}/{week_all[w]})" for w in sorted(week_all))
            or "no guard decisions in this window, so no rate") )
        if decisions and days and min(d[0] for d in decisions) > since + datetime.timedelta(days=1):
            lines.append(f"  guard.log only covers from {min(d[0] for d in decisions).date()} on: earlier days and the first week are partial")
        rules = collections.Counter(d[2] for d in asks)
        lines.append("Top ask rules: " + (", ".join(f"{r} {c}" for r, c in rules.most_common(5)) or "none"))
    actions_path = actions_path or _actions_path()
    o = ask_outcomes(actions_path, since)
    if o is None:
        lines.append("Approval rate: no action log yet")
    else:
        decided = o["approved"] + o["declined"]
        rate = f"{100 * o['approved'] / decided:.0f}% ({o['approved']} approved / {decided} decided)" if decided else "n/a (no decided asks)"
        lines.append(f"Approval rate: {rate}; unknown {o['unknown']}, unresolved {o['unresolved']} "
                     f"(of {o['asks']} asks in the action log, which keeps only notable commands; declined is inferred "
                     "when the session ends, never guessed for unknown or unresolved)")
        if os.path.exists(actions_path + ".1"):
            lines.append(f"  {actions_path}.1 exists (the log rotated at 1 MB): the window may be partial, rotated lines are not read")
    return lines


def projects_dir():
    return os.environ.get("AI_SETUP_PROJECTS_DIR") or os.path.expanduser("~/.claude/projects")


def wall_seconds(path):
    """Seconds between the first and the last timestamp of one transcript; None when it has fewer than two."""
    stamps = []
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            when = _when(d["timestamp"].replace("Z", "+00:00")) if isinstance(d, dict) and isinstance(d.get("timestamp"), str) else None
            if when:
                stamps.append(when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc))
    return (max(stamps) - min(stamps)).total_seconds() if len(stamps) > 1 else None


def _run_json():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core", "guard"))
    import run_json
    return run_json


def _dev_root():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core", "guard"))
    import guard, layers
    return layers.dev_root(guard.load())


def run_usage(run, projects=None):
    """Cost of the sessions in one run record (a dict). Never guesses: sessions without an id in the record, or without a
    transcript under projects/*/<id>.jsonl, are listed apart and add nothing. Returns a dict."""
    projects = projects or projects_dir()
    ids = [i for i in run.get("sessions") or [] if isinstance(i, str) and i and os.path.basename(i) == i]
    found, missing = {}, []
    for i in ids:
        hit = sorted(glob.glob(os.path.join(glob.escape(projects), "*", i + ".jsonl")))
        if hit:
            found[i] = hit[0]
        else:
            missing.append(i)
    s = summarize(list(found.values()))
    spans = [w for w in (wall_seconds(p) for p in found.values()) if w is not None]
    return {"sessions_listed": len(ids), "sessions_found": len(found), "missing": missing,
            "input_tokens": s["input_tokens"], "output_tokens": s["output_tokens"], "turns": s["turns"],
            "wall_seconds": sum(spans) if spans else None}


def hms(seconds):
    if seconds is None:
        return "n/a"
    m = int(round(seconds / 60))
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def ticket_report(slug, dev_root=None, projects=None):
    """Lines for `--ticket`: tokens, turns and wall time of the ticket's sessions from its run.json."""
    rj = _run_json()
    dev_root = dev_root or _dev_root()
    path = rj.run_path(dev_root, slug)
    run = rj.load(path)
    if run is None:
        return [f"Ticket {slug}: no run.json at {path}"]
    u = run_usage(run, projects)
    lines = [f"Ticket {slug} (branch {run.get('branch') or '?'}, {run.get('start') or '?'} to {run.get('end') or 'open'})"]
    if not u["sessions_listed"]:
        lines.append("  no session ids in run.json, so tokens, turns and time are unknown (ticket-flow records them with --session auto)")
        return lines
    lines.append(f"  sessions: {u['sessions_found']} of {u['sessions_listed']} with a transcript")
    if u["missing"]:
        lines.append("  no transcript for: " + ", ".join(u["missing"]) + " (not counted)")
    if u["sessions_found"]:
        total = u["input_tokens"] + u["output_tokens"]
        lines.append(f"  tokens: {total} ({u['input_tokens']} input incl. cache, {u['output_tokens']} output)  |  turns: {u['turns']}"
                     f"  |  wall time: {hms(u['wall_seconds'])}")
    return lines


def main(days=None, now=None):
    paths = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    if days:
        paths = [p for p in paths if os.path.getmtime(p) > time.time() - days * 86400]
    s = summarize(paths)
    n = max(s["sessions"], 1)
    print(f"Sessions: {s['sessions']}  |  over 150k: {s['over_150k']} ({100 * s['over_150k'] // n}%)"
          f"  |  over 300k: {s['over_300k']}  |  peak: {s['max_context'] // 1000}k")
    total = max(sum(s["models"].values()), 1)
    print("Turns by model: " + ", ".join(f"{m} {100 * c // total}%" for m, c in s["models"].most_common(4)))
    print("Top tools: " + ", ".join(f"{t} {c}" for t, c in s["tools"].most_common(6)))
    now = now or datetime.datetime.now()
    g = guard_summary(since=now - datetime.timedelta(days=days) if days else None)
    if g:
        print(f"Guard ({f'last {days} days' if days else 'all time'}): {g['allow']} allowed, {g['ask']} asked, {g['deny']} denied. "
              "Rules that fire most: " + (", ".join(f"{r} {c}" for r, c in g["rules"].most_common(5)) or "none"))
    else:
        print("Guard: no log yet (~/.ai-setup/guard.log is written when the guard runs)")
    for line in ask_report(days, now):
        print(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="?", type=int)
    ap.add_argument("--ticket")
    ap.add_argument("--dev-root")
    args = ap.parse_args()
    if args.ticket:
        try:
            print("\n".join(ticket_report(args.ticket, args.dev_root)))
        except ValueError as exc:
            ap.error(str(exc))
    else:
        main(args.days)
