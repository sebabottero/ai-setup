#!/usr/bin/env python3
"""Short table from Claude Code /insights data (~/.claude/usage-data): friction by session length, by Agent use,
by AskUserQuestion use. Reads local files only; sends nothing anywhere. Groups under MIN sessions say "few data".
Usage: python3 -I adapters/claude/tune_stats.py [usage-data dir]"""
import collections, glob, json, os, sys

MIN = 8  # smallest group worth drawing a conclusion from
DEFAULT_DIR = os.path.expanduser("~/.claude/usage-data")


def load(folder):
    """{session_id: (facet, meta)} for sessions that have both files."""
    out = {}
    for path in glob.glob(os.path.join(folder, "facets", "*.json")):
        sid = os.path.basename(path)[:-5]
        try:
            with open(path) as f:
                facet = json.load(f)
            with open(os.path.join(folder, "session-meta", sid + ".json")) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        out[sid] = (facet, meta)
    return out


def friction(facet):
    return sum((facet.get("friction_counts") or {}).values())


def length_bucket(meta):
    n = meta.get("user_message_count", 0)
    return "<=20 msgs" if n <= 20 else "21-60 msgs" if n <= 60 else ">60 msgs"


def group(sessions, key):
    groups = collections.defaultdict(list)
    for facet, meta in sessions.values():
        groups[key(facet, meta)].append(friction(facet))
    return groups


def line(label, values):
    if len(values) < MIN:
        return f"  {label:<22} n={len(values):<3} few data"
    return f"  {label:<22} n={len(values):<3} friction avg {sum(values) / len(values):.1f}"


def report(sessions):
    if not sessions:
        return "No sessions with facets and meta: run /insights first."
    kinds = collections.Counter()
    for facet, _ in sessions.values():
        kinds.update(facet.get("friction_counts") or {})
    rows = [f"Sessions: {len(sessions)}", "Top friction: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common(5))]
    tests = {
        "By length": lambda f, m: length_bucket(m),
        "Agent used": lambda f, m: "with Agent" if (m.get("tool_counts") or {}).get("Agent") else "no Agent",
        "AskUserQuestion used": lambda f, m: "with questions" if (m.get("tool_counts") or {}).get("AskUserQuestion") else "no questions",
        "By session type": lambda f, m: f.get("session_type", "?"),
    }
    for title, key in tests.items():
        rows.append(title)
        rows += [line(k, v) for k, v in sorted(group(sessions, key).items())]
    return "\n".join(rows)


if __name__ == "__main__":
    print(report(load(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR)))
