#!/usr/bin/env python3
"""Local usage report from Claude Code transcripts: how many sessions grow past 150k tokens, which models
run the turns, which tools dominate. Reads ~/.claude/projects only; sends nothing anywhere.
Usage: python3 -I adapters/claude/usage_report.py [days]   (default: all transcripts)"""
import collections, glob, json, os, sys, time

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


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
