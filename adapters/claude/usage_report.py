#!/usr/bin/env python3
"""Local usage report from Claude Code transcripts: how many sessions grow past 150k tokens, which models
run the turns, which tools dominate. Reads ~/.claude/projects only; sends nothing anywhere.
Usage: python3 -I adapters/claude/usage_report.py [days]   (default: all transcripts)"""
import collections, datetime, glob, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "core", "guard"))

LIMIT = 150_000
TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def summarize(paths):
    models, tools = collections.Counter(), collections.Counter()
    contexts, output = [], 0
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
                peak = max(peak, sum(usage.get(k, 0) for k in TOKEN_KEYS))
                output += usage.get("output_tokens", 0)
                models[msg.get("model", "?")] += 1
            for block in msg.get("content") if isinstance(msg.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
        if peak:
            contexts.append(peak)
    return {"sessions": len(contexts), "over_150k": sum(c > LIMIT for c in contexts),
            "over_300k": sum(c > 2 * LIMIT for c in contexts), "max_context": max(contexts, default=0),
            "output_tokens": output, "models": models, "tools": tools}


def guard_summary(path=None):
    """Counts from the guard log (time, tool, decision, rule per line); None if there is no log yet."""
    path = path or os.environ.get("AI_SETUP_GUARD_LOG") or os.path.expanduser("~/.ai-setup/guard.log")
    counts, rules = collections.Counter(), collections.Counter()
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 4 and parts[2] in ("allow", "ask", "deny"):
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


def ask_outcomes(path=None, since=None):
    """How the asks in the action log ended (guard.actions_log_path unless a path is given). Outcome lines are linked to
    the `asked` line by session + command, oldest first; the ask's own time is the decision time (a `declined` line is
    stamped when it was inferred). Returns None without a log, else {approved, declined, unknown, unresolved, asks}.
    Old lines without outcomes count as unresolved."""
    if path is None:
        import guard
        path = guard.actions_log_path()
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
            result["asks_all"] += 1
            outcome = outcomes[key].popleft() if outcomes[key] else None  # oldest ask takes the oldest outcome
            if since is not None and when < since:
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
    o = ask_outcomes(actions_path, since)
    if o is None:
        lines.append("Approval rate: no action log yet")
    else:
        decided = o["approved"] + o["declined"]
        rate = f"{100 * o['approved'] / decided:.0f}% ({o['approved']} approved / {decided} decided)" if decided else "n/a (no decided asks)"
        lines.append(f"Approval rate: {rate}; unknown {o['unknown']}, unresolved {o['unresolved']} "
                     f"(of {o['asks']} asks in the action log, which keeps only notable commands; declined is inferred "
                     "when the session ends, never guessed for unknown or unresolved)")
    return lines


def main(days=None):
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
    g = guard_summary()
    if g:
        print(f"Guard: {g['allow']} allowed, {g['ask']} asked, {g['deny']} denied. "
              "Rules that fire most: " + (", ".join(f"{r} {c}" for r, c in g["rules"].most_common(5)) or "none"))
    else:
        print("Guard: no log yet (~/.ai-setup/guard.log is written when the guard runs)")
    for line in ask_report(days):
        print(line)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
