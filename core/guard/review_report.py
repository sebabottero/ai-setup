#!/usr/bin/env python3
"""Review reports: where sub-review writes them, what they say, and the git facts the merge gate compares them with.

  python3 -I review_report.py header [--dir D] [--dev-root DIR] [--verdict PASS|FAIL|"NEEDS CHANGES"]
    first line: the report path (<dev_root>/reviews/<repo>/<branch>.md); then the header block to paste at the top of it.
    An earlier non-empty report at that path is first copied to <branch>.r<N>.md (next N), so every round is kept and the
    newest stays at <branch>.md; running header again without a new report in between adds nothing.
  python3 -I review_report.py log --stage 3|4 [--dir D] [--dev-root DIR]
    appends one line to <dev_root>/logs/reviews.log (tab separated: time, repo, branch, round, stage, verdict, findings
    per severity, triage counts) from the report just written. Severities are read from the issues table's severity column:
    new (blocking/major/minor/nit) and old (Critical/Warning/Nit); triage (fix_now/defer/reject) from its triage column.
  python3 -I review_report.py rounds --stage 3|4 [--dir D] [--dev-root DIR]
    prints `stage=N rounds=R open=O stop=yes|no` for the branch, from reviews.log: rounds logged for that stage, blocking +
    major findings of the last one; stop=yes (2+ rounds and still open) means ticket-flow must not start another round.

A report is fresh when its `Commit:` is the branch head, or its `Tree:` is the head's tree (work reviewed before it was committed).
"""
import argparse, datetime, glob, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))


def git(directory, *args, env=None):
    """Stdout of a git command run in directory, or None when it fails or times out."""
    try:
        run = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=3, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return run.stdout.strip() if run.returncode == 0 else None


def repo_name(directory):
    """Name of the main repo, also from a worktree: the folder that holds the common .git."""
    common = git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.basename(os.path.dirname(common.rstrip("/"))) if common else None


def report_path(dev_root, repo, branch):
    return os.path.join(os.path.expanduser(dev_root), "reviews", repo, branch + ".md")


def worktree_tree(directory):
    """Tree id of the working tree, untracked files included (ignored ones not), without touching the real index."""
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        if git(directory, "read-tree", "HEAD", env=env) is None or git(directory, "add", "-A", env=env) is None:
            return None
        return git(directory, "write-tree", env=env)


def parse(text):
    """{'commit', 'tree', 'verdict'} from the first header line of each kind; a bullet (`- `) and markdown bold are read
    too, and the verdict is the whole value (`NEEDS CHANGES`). Missing ones are ''."""
    found = {"commit": "", "tree": "", "verdict": ""}
    for line in text.splitlines():
        m = re.match(r"\s*(?:[-*+]\s+)?[*_]*(Commit|Tree|Verdict)[*_]*\s*:[*_\s]*(.*?)[*_\s]*$", line, re.I)
        if m and not found[m.group(1).lower()]:
            value = m.group(2)
            found[m.group(1).lower()] = value if m.group(1).lower() == "verdict" else value.split(" ")[0]
    return found


def rounds(path):
    """Archived rounds of a report: {N: path} for <branch>.r<N>.md next to <branch>.md."""
    base, found = path[:-3], {}
    for other in glob.glob(glob.escape(base) + ".r*.md"):
        m = re.fullmatch(r"\d+", other[len(base) + 2:-3])
        if m:
            found[int(m.group())] = other
    return found


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def archive(path):
    """Copy a non-empty report to the next .r<N>.md unless the newest round already holds the same text. A copy, not a
    move: <branch>.md stays, so the merge gate never sees the report missing."""
    text = read(path)
    if not text.strip():
        return
    kept = rounds(path)
    if kept and read(kept[max(kept)]) == text:
        return
    with open(f"{path[:-3]}.r{max(kept, default=0) + 1}.md", "w", encoding="utf-8") as f:
        f.write(text)


SEVERITIES = ["critical", "warning", "blocking", "major", "minor", "nit"]
TRIAGES = ["fix_now", "defer", "reject"]
OPEN = {"blocking", "major", "critical", "warning"}  # what keeps a round open; critical / warning are the old words


def table_rows(text):
    """(severity, triage) of each data row of the issues tables. A header row (the one before a `---` row) is skipped; its
    `severity` / `triage` cells say which columns to read (default: severity first, no triage, as in old reports)."""
    lines = [l.strip() for l in text.splitlines()]
    sev, tri = 0, None
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            sev, tri = 0, None
            continue
        cells = [c.strip().strip("*_` ").lower() for c in line.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells if c) and any(cells):
            continue
        if i + 1 < len(lines) and lines[i + 1].startswith("|") and re.fullmatch(r"[|\s:-]+", lines[i + 1]):
            sev = cells.index("severity") if "severity" in cells else 0
            tri = cells.index("triage") if "triage" in cells else None
            continue
        if sev < len(cells) and cells[sev] in SEVERITIES:
            yield cells[sev], cells[tri] if tri is not None and tri < len(cells) else ""


def findings(text):
    """{severity: count} from the severity column of the issues table rows; headers and any other row are ignored."""
    found = {}
    for severity, _ in table_rows(text):
        found[severity] = found.get(severity, 0) + 1
    return found


def triage(text):
    """{fix_now|defer|reject: count} from the triage column of the issues table; old reports have none."""
    found = {}
    for _, value in table_rows(text):
        if value in TRIAGES:
            found[value] = found.get(value, 0) + 1
    return found


def log(directory, dev_root, stage):
    """Append the review line to <dev_root>/logs/reviews.log; the line is returned."""
    branch = git(directory, "symbolic-ref", "-q", "--short", "HEAD") or "HEAD"
    repo = repo_name(directory) or "?"
    path = report_path(dev_root, repo, branch)
    text = read(path)
    if not text.strip():
        sys.exit(f"error: no report to log at {path}; write it first")
    counts, picked = findings(text), triage(text)
    found = " ".join(f"{k}={counts[k]}" for k in SEVERITIES if k in counts) or "none"
    sorted_out = " ".join(f"{k}={picked[k]}" for k in TRIAGES if k in picked) or "none"
    kept = rounds(path)
    # header copies the old report to rN before the new one is written: a report equal to the newest rN is still that round
    number = max(kept) if kept and read(kept[max(kept)]) == text else len(kept) + 1
    # fields are append-only: new ones go at the end (triage counts came after the findings)
    line = "\t".join([datetime.datetime.now().isoformat(timespec="seconds"), repo, branch, str(number),
                      str(stage), parse(text)["verdict"] or "?", found, sorted_out])
    logs = os.path.join(os.path.expanduser(dev_root), "logs")
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "reviews.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def stage_rounds(directory, dev_root, stage):
    """`stage=N rounds=R open=O stop=yes|no` for this branch from reviews.log: R distinct rounds logged for the stage, O the
    blocking + major findings (old critical + warning too) of the last of them; stop=yes when R >= 2 and O > 0."""
    branch = git(directory, "symbolic-ref", "-q", "--short", "HEAD") or "HEAD"
    repo = repo_name(directory) or "?"
    seen = {}
    for entry in read(os.path.join(os.path.expanduser(dev_root), "logs", "reviews.log")).splitlines():
        f = entry.split("\t")
        if len(f) >= 7 and f[1] == repo and f[2] == branch and f[4] == str(stage):
            seen[f[3]] = f[6]  # a round logged twice counts once; the later line wins
    last = seen[max(seen, key=lambda n: int(n) if n.isdigit() else 0)] if seen else ""
    open_ = sum(int(n) for k, n in re.findall(r"(\w+)=(\d+)", last) if k in OPEN)
    return f"stage={stage} rounds={len(seen)} open={open_} stop={'yes' if len(seen) >= 2 and open_ else 'no'}"


def header(directory, dev_root, verdict=""):
    branch = git(directory, "symbolic-ref", "-q", "--short", "HEAD") or "HEAD"
    repo = repo_name(directory) or "?"
    archive(report_path(dev_root, repo, branch))
    tree = worktree_tree(directory)
    if not tree:
        print("warning: could not compute the tree of the working tree; the report will match by commit only", file=sys.stderr)
    lines = [report_path(dev_root, repo, branch), "", f"Repo: {repo}", f"Branch: {branch}",
             f"Commit: {git(directory, 'rev-parse', 'HEAD') or '?'}", f"Tree: {tree or ''}"]
    if verdict:
        lines.append(f"Verdict: {verdict}")
    lines += ["Reviewer: sub-review", f"Date: {datetime.datetime.now().isoformat(timespec='seconds')}"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["header", "log", "rounds"])
    ap.add_argument("--stage", choices=["3", "4"])
    ap.add_argument("--dir", default=".")
    ap.add_argument("--dev-root")
    ap.add_argument("--verdict", default="", choices=["", "PASS", "FAIL", "NEEDS CHANGES"])
    args = ap.parse_args()
    dev_root = args.dev_root
    if not dev_root:
        try:
            import guard, layers
            dev_root = layers.dev_root(guard.load())
        except Exception:
            dev_root = "~"
    if args.command in ("log", "rounds") and not args.stage:
        ap.error(f"{args.command} needs --stage 3|4")
    if args.command == "rounds":
        print(stage_rounds(args.dir, dev_root, args.stage))
        return
    if args.command == "log":
        print(log(args.dir, dev_root, args.stage))
        return
    print(header(args.dir, dev_root, args.verdict))


if __name__ == "__main__":
    main()
