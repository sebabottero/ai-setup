#!/usr/bin/env python3
"""Review reports: where sub-review writes them, what they say, and the git facts the merge gate compares them with.

  python3 -I review_report.py header [--dir D] [--dev-root DIR] [--verdict PASS|FAIL|"NEEDS CHANGES"]
    first line: the report path (<dev_root>/reviews/<repo>/<branch>.md); then the header block to paste at the top of it.

A report is fresh when its `Commit:` is the branch head, or its `Tree:` is the head's tree (work reviewed before it was committed).
"""
import argparse, datetime, os, re, subprocess, sys, tempfile

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


def header(directory, dev_root, verdict=""):
    branch = git(directory, "symbolic-ref", "-q", "--short", "HEAD") or "HEAD"
    repo = repo_name(directory) or "?"
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
    ap.add_argument("command", choices=["header"])
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
    print(header(args.dir, dev_root, args.verdict))


if __name__ == "__main__":
    main()
