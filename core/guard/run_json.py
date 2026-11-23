#!/usr/bin/env python3
"""Run record of a ticket: <dev root>/handoffs/<ticket>/run.json. ticket-flow writes it at 0a and updates it at each gate.
A light journal for reading afterwards; nothing resumes from it.

  python3 -I run_json.py update <ticket> [--dev-root DIR] [--session ID] [--branch B] [--pr N] [--report PATH]
                                         [--round STAGE:VERDICT[:REPORT]] [--end]
    creates the file on the first call (start time = now); every later call adds to it.
    --session / --report  appended once (a repeated value is not duplicated)
    --round               one review round: stage (3 or 4), verdict, report path; `n` counts the rounds of that stage
    --end                 sets the end time
  python3 -I run_json.py show <ticket> [--dev-root DIR]

Fields: ticket, sessions[], branch, pr, reports[], rounds[{stage, n, verdict, report}], start, end (ISO times)."""
import argparse, datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def check_ticket(ticket):
    """The ticket is a folder name under handoffs/: no separators, no `.` / `..`, no leading dot."""
    if not ticket or "/" in ticket or "\\" in ticket or ticket.startswith(".") or "\0" in ticket:
        raise ValueError(f"ticket must be a plain folder name (no '/', no leading '.'): {ticket!r}")
    return ticket


def run_path(dev_root, ticket):
    check_ticket(ticket)
    return os.path.join(os.path.expanduser(dev_root), "handoffs", ticket, "run.json")


def load(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def update(dev_root, ticket, session=None, branch=None, pr=None, report=None, rounds=(), end=False):
    """Create or extend the run record; returns it. Each of rounds is (stage, verdict, report_path_or_None)."""
    path = run_path(dev_root, ticket)
    run = load(path) or {"ticket": ticket, "sessions": [], "branch": None, "pr": None, "reports": [], "rounds": [],
                         "start": now(), "end": None}
    if session and session not in run["sessions"]:
        run["sessions"].append(session)
    if branch:
        run["branch"] = branch
    if pr is not None:
        run["pr"] = pr
    if report and report not in run["reports"]:
        run["reports"].append(report)
    for stage, verdict, rpath in rounds:
        n = 1 + sum(1 for r in run["rounds"] if r.get("stage") == stage)
        run["rounds"].append({"stage": stage, "n": n, "verdict": verdict, "report": rpath})
        if rpath and rpath not in run["reports"]:
            run["reports"].append(rpath)
    if end:
        run["end"] = now()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(run, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return run


def parse_round(text):
    parts = text.split(":", 2)
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1]:
        raise argparse.ArgumentTypeError("--round wants STAGE:VERDICT[:REPORT], for example 3:PASS:/path/x.md")
    return int(parts[0]), parts[1], parts[2] if len(parts) > 2 and parts[2] else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["update", "show"])
    ap.add_argument("ticket")
    ap.add_argument("--dev-root")
    ap.add_argument("--session")
    ap.add_argument("--branch")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--report")
    ap.add_argument("--round", dest="rounds", type=parse_round, action="append", default=[])
    ap.add_argument("--end", action="store_true")
    args = ap.parse_args(argv)
    try:
        check_ticket(args.ticket)
    except ValueError as exc:
        ap.error(str(exc))
    dev_root = args.dev_root
    if not dev_root:
        try:
            import guard, layers
            dev_root = layers.dev_root(guard.load())
        except Exception as exc:  # writing into the wrong folder is worse than not writing
            ap.error(f"cannot read the dev root from the policy ({exc}); pass --dev-root DIR")
    if args.command == "show":
        print(json.dumps(load(run_path(dev_root, args.ticket)), indent=2))
        return
    run = update(dev_root, args.ticket, args.session, args.branch, args.pr, args.report, args.rounds, args.end)
    print(run_path(dev_root, args.ticket))


if __name__ == "__main__":
    main()
