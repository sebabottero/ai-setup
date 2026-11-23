#!/usr/bin/env python3
"""Weekly view of how the harness is working: the 5 measures of the gap analysis, from the logs you already have.

  python3 -I core/scripts/metrics.py --week [2026-W47] [--dev-root DIR]
    writes <dev root>/logs/metrics-<YYYY-Www>.md (the current ISO week when none is given) and prints its path.

Reads: <dev root>/logs/reviews.log, actions.log (AI_SETUP_ACTIONS_LOG), guard.log (AI_SETUP_GUARD_LOG), the run.json files
under <dev root>/handoffs/*/, the transcripts the run.json session ids point to (AI_SETUP_PROJECTS_DIR), and `git log` of
<dev root>/repos/<repo> (read only). Writes only the metrics file; no log is rewritten. Reviews.log overrides: AI_SETUP_REVIEWS_LOG.

Measures: rounds to PASS per branch, ask answers, runs per ticket, tokens and time per ticket, findings by severity and triage."""
import argparse, collections, datetime, glob, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude"))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import usage_report, run_json  # noqa: E402


def week_bounds(label):
    """('2026-W47') -> (monday 00:00, next monday 00:00)."""
    m = re.fullmatch(r"(\d{4})-W(\d{2})", label or "")
    if not m:
        raise ValueError(f"week must look like 2026-W47: {label!r}")
    start = datetime.datetime.fromisocalendar(int(m[1]), int(m[2]), 1)
    return start, start + datetime.timedelta(days=7)


def current_week(now=None):
    iso = (now or datetime.datetime.now()).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def read_lines(path):
    try:
        with open(path, errors="ignore") as f:
            return f.read().splitlines()
    except OSError:
        return None


def pairs(text):
    """'minor=2 nit=1' -> {'minor': 2, 'nit': 1}; 'none' and anything else -> {}."""
    return {k: int(n) for k, n in re.findall(r"(\w+)=(\d+)", text or "")}


def review_entries(lines):
    """[(time, repo, branch, round, stage, verdict, findings{}, triage{})]: new 8-field lines and older 7-field ones."""
    out = []
    for line in lines or []:
        f = line.split("\t")
        when = usage_report._when(f[0]) if len(f) >= 7 else None
        if when:
            out.append((when, f[1], f[2], f[3], f[4], f[5], pairs(f[6]), pairs(f[7]) if len(f) > 7 else {}))
    return out


def rounds_to_pass(entries, start, end):
    """Per (repo, branch, stage) with a review line in the week: distinct rounds up to the first PASS (all time),
    or the rounds so far when it has not passed. Returns [(repo, branch, stage, rounds, passed)]."""
    keys = sorted({(e[1], e[2], e[4]) for e in entries if start <= e[0] < end})
    out = []
    for repo, branch, stage in keys:
        seen, passed = set(), False
        for e in sorted((e for e in entries if e[1:3] == (repo, branch) and e[4] == stage), key=lambda e: e[0]):
            seen.add(e[3])
            if e[5] == "PASS":
                passed = True
                break
        out.append((repo, branch, stage, len(seen), passed))
    return out


def git_commits(repos_dir, repo, branch, start, end):
    """The branch's own commits in the week (git log origin/main..branch, else main..branch; read only); None when the
    repo, the branch or the base ref is not there: never the full history."""
    # both come from a log line: the repo must be a plain folder name under repos/, the branch must not look like an option
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", repo or "") or repo == ".." or not branch or branch.startswith("-") \
            or re.search(r"[\x00-\x1f\x7f ]", branch):
        return None
    path = os.path.join(repos_dir, repo)
    if not os.path.isdir(path) or os.path.islink(path):
        return None
    try:
        base = None
        for ref in ("origin/main", "main"):  # the branch's own commits are the ones its base does not have
            if subprocess.run(["git", "-C", path, "rev-parse", "--verify", "--quiet", "--end-of-options", ref + "^{commit}"],
                              capture_output=True, timeout=10).returncode == 0:
                base = ref
                break
        if base is None or branch == base:
            return None
        run = subprocess.run(["git", "-C", path, "log", "--oneline", f"--since={start.isoformat()}",
                              f"--until={end.isoformat()}", "--end-of-options", f"{base}..{branch}", "--"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return len(run.stdout.split("\n")) - 1 if run.returncode == 0 else None


def run_records(dev_root):
    """([(ticket, run)], skipped): a run.json that is not a JSON object, or whose start is not a parseable string, is skipped."""
    out, skipped = [], 0
    for path in sorted(glob.glob(os.path.join(glob.escape(dev_root), "handoffs", "*", "run.json"))):
        run = run_json.load(path)
        if run is None or usage_report._when(run.get("start")) is None:
            skipped += 1
            continue
        out.append((os.path.basename(os.path.dirname(path)), run))
    return out, skipped


def in_week(run, start, end):
    """A run belongs to the week when it overlapped it: started before the end and not finished before the start."""
    begin = usage_report._when(run.get("start"))
    finish = usage_report._when(run.get("end"))  # a missing or unreadable end counts as still open
    return begin is not None and begin < end and (finish is None or finish >= start)


def count(run, key):
    return len(run[key]) if isinstance(run.get(key), list) else 0


TOP_N = 15
PREFIX_WORDS = {"cd", "export", "pushd", "set", "unset", "source", "."}  # setup words, not the command that did the work
NO_HEAD = "(no command word)"


def command_head(command):
    """First real command of a logged command line: skips FOO=1 assignments and cd/export-style setup segments, and
    reduces a path to its basename. Splits on text, not shell rules: the line is redacted and may be cut at 240 chars."""
    for seg in re.split(r"&&|\|\||[;|\n]", command):
        words = seg.lstrip(" \t({!").split()
        while words and re.fullmatch(r"[A-Za-z_]\w*=\S*", words[0]):
            words.pop(0)
        if not words or words[0] in PREFIX_WORDS:
            continue
        return os.path.basename(words[0].strip("\"'")) or words[0]
    return NO_HEAD


def outside_sandbox(lines, start, end):
    """Counter of command heads for the actions.log lines that ran outside the sandbox without asking
    (6 fields, MEDIUM, `ran`, rule `outside-sandbox`) at a time inside [start, end)."""
    heads = collections.Counter()
    for line in lines or []:
        f = line.split("\t")
        if len(f) == 6 and f[2] == "MEDIUM" and f[3] == "ran" and f[4] == "outside-sandbox":
            when = usage_report._when(f[0])
            if when and start <= when < end:
                heads[command_head(f[5])] += 1
    return heads


def build(dev_root, label, projects=None, reviews_path=None, actions_path=None, guard_path=None):
    start, end = week_bounds(label)
    dev_root = os.path.expanduser(dev_root)
    logs = os.path.join(dev_root, "logs")
    reviews_path = reviews_path or os.environ.get("AI_SETUP_REVIEWS_LOG") or os.path.join(logs, "reviews.log")
    actions_path = actions_path or os.environ.get("AI_SETUP_ACTIONS_LOG") or os.path.join(logs, "actions.log")
    guard_path = guard_path or usage_report._guard_log_path()
    md = [f"# Harness metrics {label}", "", f"Week {start.date()} to {(end - datetime.timedelta(days=1)).date()} "
          f"(ISO, Monday to Sunday). Generated {datetime.datetime.now().isoformat(timespec='minutes')} from local logs; "
          "nothing was rewritten.", ""]

    review_lines = read_lines(reviews_path)
    entries = review_entries(review_lines)
    week = [e for e in entries if start <= e[0] < end]

    md += ["## 1. Rounds to PASS per branch", ""]
    if review_lines is None:
        md.append(f"No reviews.log at {reviews_path}.")
    elif not week:
        md.append("No review lines this week.")
    else:
        md += ["| repo | branch | stage | rounds | result |", "|---|---|---|---|---|"]
        repos_dir = os.path.join(dev_root, "repos")
        for repo, branch, stage, n, passed in rounds_to_pass(entries, start, end):
            md.append(f"| {repo} | {branch} | {stage} | {n} | {'PASS' if passed else 'not PASS yet'} |")
        md += ["", "Commits on those branches this week (git log): " + ", ".join(
            f"{b} {'n/a' if c is None else c}" for r, b in sorted({(e[1], e[2]) for e in week})
            for c in [git_commits(repos_dir, r, b, start, end)])]
    md.append("")

    md += ["## 2. Ask answers", ""]
    o = usage_report.ask_outcomes(actions_path, start, end)
    if o is None:
        md.append(f"No actions.log at {actions_path}.")
    else:
        decided = o["approved"] + o["declined"]
        rate = f"{100 * o['approved'] / decided:.0f}%" if decided else "n/a"
        md.append(f"Asks in the action log: {o['asks']} | approved {o['approved']} | declined {o['declined']} | "
                  f"unknown {o['unknown']} | unresolved {o['unresolved']} | approval rate {rate}")
        md.append("Declined is stamped when the session ends; each ask is dated by its own `asked` line.")
    decisions = usage_report.guard_decisions(guard_path)
    if decisions is not None:
        c = collections.Counter(d[1] for d in decisions if start <= d[0] < end)
        md.append(f"Guard decisions this week: {c['allow']} allow, {c['ask']} ask, {c['deny']} deny.")
    md.append("")

    records, skipped = run_records(dev_root)
    runs = [(slug, run) for slug, run in records if in_week(run, start, end)]
    md += ["## 3. Runs per ticket", ""]
    if not runs:
        md.append("No run.json active this week.")
    else:
        md += ["| ticket | branch | pr | sessions | rounds | start | end |", "|---|---|---|---|---|---|---|"]
        for slug, run in runs:
            md.append(f"| {slug} | {run.get('branch') or '?'} | {run.get('pr') or '-'} | {count(run, 'sessions')} | "
                      f"{count(run, 'rounds')} | {run.get('start')} | {run.get('end') or 'open'} |")
    if skipped:
        md += ["", f"Skipped {skipped} run.json files (not a JSON object, or `start` missing or not a readable time)."]
    md.append("")

    md += ["## 4. Tokens and time per ticket", ""]
    if not runs:
        md.append("No tickets this week.")
    else:
        md += ["| ticket | sessions with transcript | tokens | turns | wall time |", "|---|---|---|---|---|"]
        for slug, run in runs:
            u = usage_report.run_usage(run, projects)
            if not u["sessions_listed"]:
                md.append(f"| {slug} | none (no session ids in run.json) | unknown | unknown | unknown |")
                continue
            note = f" (no transcript: {', '.join(u['missing'])})" if u["missing"] else ""
            md.append(f"| {slug} | {u['sessions_found']} of {u['sessions_listed']}{note} | "
                      + (f"{u['input_tokens'] + u['output_tokens']} | {u['turns']} | {usage_report.hms(u['wall_seconds'])} |"
                         if u["sessions_found"] else "unknown | unknown | unknown |"))
    md.append("")

    md += ["## 5. Findings by severity and triage", ""]
    sev, tri = collections.Counter(), collections.Counter()
    for e in week:
        sev.update(e[6])
        tri.update(e[7])
    if not week:
        md.append("No review lines this week.")
    else:
        md.append("Severity: " + (", ".join(f"{k} {v}" for k, v in sev.most_common()) or "none"))
        md.append("Triage: " + (", ".join(f"{k} {v}" for k, v in tri.most_common()) or "none recorded (older lines have no triage)"))
        md.append(f"Counted over {len(week)} review lines, one per round logged; a finding that stays open is counted again each round.")
    md.append("")

    md += ["## Outside-sandbox commands", ""]
    heads = outside_sandbox(read_lines(actions_path), start, end)
    if not heads:
        md.append("none")
    else:
        total = sum(heads.values())
        ranked = sorted(heads.items(), key=lambda kv: (-kv[1], kv[0]))
        md += ["| command | ran |", "|---|---|"] + [f"| {h} | {n} |" for h, n in ranked[:TOP_N]]
        rest = ranked[TOP_N:]
        if rest:
            md.append(f"| other ({len(rest)} commands) | {sum(n for _, n in rest)} |")
        md += ["", f"Total: {total} commands ran outside the sandbox without asking (MEDIUM `outside-sandbox`), "
                   "grouped by command head. Command text is shown as the log redacted it."]
    md.append("")
    return "\n".join(md)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", nargs="?", const="", default="", help="ISO week such as 2026-W47 (default: this week)")
    ap.add_argument("--dev-root")
    args = ap.parse_args(argv)
    label = args.week or current_week()
    dev_root = args.dev_root
    if not dev_root:
        try:
            dev_root = usage_report._dev_root()
        except Exception as exc:  # writing into the wrong folder is worse than not writing
            ap.error(f"cannot read the dev root from the policy ({exc}); pass --dev-root DIR")
    try:
        text = build(dev_root, label)
    except ValueError as exc:
        ap.error(str(exc))
    logs = os.path.join(os.path.expanduser(dev_root), "logs")
    os.makedirs(logs, exist_ok=True)
    path = os.path.join(logs, f"metrics-{label}.md")
    if os.path.islink(path):
        ap.error(f"{path} is a symlink; refusing to write through it")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(path)


if __name__ == "__main__":
    main()
