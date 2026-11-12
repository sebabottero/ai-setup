#!/usr/bin/env python3
"""ai-audit: score a repo against 8 generic practices. Read-only, stdlib only, stdout only.

Usage: python3 -I audit.py <repo> [--today YYYY-MM-DD] [--projects-dir DIR] [--dev-root DIR]

Scores are 1-5 heuristics (or n/a when the data is missing), a conversation starter and not a grade.
Nothing is ever written: git runs read-only commands and everything else is a file read.
"""
import argparse, datetime, fnmatch, glob, json, os, re, subprocess, sys

PRACTICES = [
    "Independent review", "Tests tied to intent", "Enforced rules", "Real static checks",
    "Shared knowledge", "Small changes", "CI covers what matters", "Human gate",
]
BIG_COMMIT = 400
SUB_REVIEW_CALL = re.compile(r'"subagent_type"\s*:\s*"sub-review"')
LINTERS = {  # tool -> config file globs
    "eslint": [".eslintrc*", "eslint.config.*"],
    "ruff": ["ruff.toml", ".ruff.toml"],
    "flake8": [".flake8"],
    "pylint": [".pylintrc"],
    "biome": ["biome.json", "biome.jsonc"],
    "rubocop": [".rubocop.yml"],
    "stylelint": [".stylelintrc*", "stylelint.config.*"],
    "golangci-lint": [".golangci.*"],
    "tslint": ["tslint.json"],
}
DISABLE = re.compile(r"\b(eslint|stylelint|pylint|rubocop|tslint)(?:-|:\s*)disable")
DEP_FILES = ["package.json", "pyproject.toml", "requirements*.txt", "Pipfile", "Gemfile", "go.mod", "setup.cfg", "tox.ini"]


def score_from_share(share):
    return 1 + round(4 * share)


def git(repo, *args):
    """Read-only git. Returns stdout, or None when git or the repo is unavailable."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    try:
        proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, env=env)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def read_text(path, limit=1_000_000):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def list_files(repo):
    """Repo-relative file paths: tracked files, or a plain walk when there is no git."""
    out = git(repo, "ls-files")
    if out is not None:
        return [p for p in out.splitlines() if p and os.path.isfile(os.path.join(repo, p))]
    found = []
    for base, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", "venv")]
        found += [os.path.relpath(os.path.join(base, f), repo) for f in files]
    return found


def is_test_file(path):
    parts = path.lower().split("/")
    name = parts[-1]
    return "test" in name or "spec" in name or any(p in ("tests", "test", "__tests__", "spec") for p in parts[:-1])


def repo_names(repo):
    """The folder name, plus the main repo's name when `repo` is a git worktree."""
    names = [os.path.basename(repo)]
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        main = os.path.basename(os.path.dirname(common.strip().rstrip("/")))
        if main and main not in names:
            names.append(main)
    return names


def has_sub_review(log):
    """True/False for a readable session log (read line by line), None when it cannot be read."""
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            return any(SUB_REVIEW_CALL.search(line) for line in f)
    except OSError:
        return None


# 1 -------------------------------------------------------------------------------------------------
def review(ctx):
    names = [n.lower() for n in ctx["names"]]
    sessions = reviewed = 0
    pdir = ctx["projects_dir"]
    if os.path.isdir(pdir):
        for d in sorted(os.listdir(pdir)):
            # project folders are the path with "/" turned into "-": match the name as the tail, not anywhere
            if not any(d.lower() == n or d.lower().endswith("-" + n) for n in names):
                continue
            for log in glob.glob(os.path.join(pdir, d, "*.jsonl")):
                found = has_sub_review(log)
                if found is None:
                    continue
                sessions += 1
                reviewed += found
    reports = sum(len(glob.glob(os.path.join(ctx["dev_root"], "reviews", n, "*.md"))) for n in ctx["names"])
    if not sessions:
        return "n/a", f"no session logs for '{ctx['names'][0]}' under {pdir}; {reports} review reports"
    return (str(score_from_share(reviewed / sessions)),
            f"{reviewed} of {sessions} sessions called sub-review; {reports} review reports in reviews/{ctx['names'][0]}/")


# 2 -------------------------------------------------------------------------------------------------
def tests_intent(ctx):
    names = [n.lower() for n in ctx["names"]]
    criteria = [p for p in ctx["files"] if os.path.basename(p).lower() == "criteria.md"]
    handoffs = [p for p in glob.glob(os.path.join(ctx["dev_root"], "handoffs", "*", "criteria.md"))
                if any(os.path.basename(os.path.dirname(p)).lower() in (n,) or
                       os.path.basename(os.path.dirname(p)).lower().startswith(n + "-") for n in names)]
    tests = [p for p in ctx["files"] if is_test_file(p)]
    mapped = [p for p in tests if re.search(r"criteri|given|test_\d+_", p.lower())
              or re.search(r"(def |it\(|test\()\s*['\"]?(test_\d+_|given|when_)", read_text(os.path.join(ctx["repo"], p)) or "", re.I)]
    have = bool(criteria or handoffs)
    if have and mapped:
        score = 5
    elif have and tests:
        score = 4
    elif have:
        score = 3
    elif mapped:
        score = 2
    else:
        score = 1
    where = (criteria + handoffs)[:1]
    return str(score), (f"criteria: {where[0] if where else 'none'}; {len(tests)} test files, "
                        f"{len(mapped)} named after criteria")


# 3 -------------------------------------------------------------------------------------------------
def parse_rules(ctx):
    """Rules from AGENTS.md: list of (line, text), plus the line of the Rules heading (or None)."""
    text = read_text(os.path.join(ctx["repo"], "AGENTS.md"))
    if text is None:
        return None, None, []
    rules, heading, inside = [], None, False
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            inside = line[3:].strip().lower().startswith("rules")
            if inside:
                heading = n
        elif inside and line.startswith("- "):
            rules.append((n, line[2:].strip()))
    return text, heading, rules


def classify(rules, today):
    enforced, dated, unmarked, expired, invalid = [], [], [], [], []
    for n, text in rules:
        if text.startswith("E:"):
            enforced.append(n)
            continue
        m = re.search(r"\(until ([^)]*)\)", text)
        until = None
        if m:
            try:
                until = datetime.date.fromisoformat(m.group(1).strip())
            except ValueError:
                invalid.append((n, text))
        if until is None:
            unmarked.append(n)
        elif until < today:
            expired.append((n, text))
        else:
            dated.append(n)
    return enforced, dated, unmarked, expired, invalid


def enforced_rules(ctx):
    text, heading, rules = parse_rules(ctx)
    if text is None:
        return "1", "no AGENTS.md", [], []
    if not rules:
        why = "AGENTS.md has no Rules section with rules" if heading is None else f"AGENTS.md:{heading} Rules section is empty"
        return "1", why, [], []
    enforced, dated, unmarked, expired, invalid = classify(rules, ctx["today"])
    score = score_from_share((len(enforced) + len(dated)) / len(rules))
    return (str(score), f"AGENTS.md:{heading}: {len(rules)} rules: {len(enforced)} E, {len(dated)} dated, "
                        f"{len(unmarked)} unmarked, {len(expired)} expired"
                        + (f", {len(invalid)} invalid dates" if invalid else ""), expired, invalid)


# 4 -------------------------------------------------------------------------------------------------
def static_checks(ctx):
    files = ctx["files"]
    basenames = [os.path.basename(p) for p in files]
    configured = []
    for tool, globs in LINTERS.items():
        if any(fnmatch.fnmatch(b, g) for b in basenames for g in globs):
            configured.append(tool)
    pyproject = read_text(os.path.join(ctx["repo"], "pyproject.toml")) or ""
    for tool in ("ruff", "pylint", "flake8"):
        if f"[tool.{tool}" in pyproject and tool not in configured:
            configured.append(tool)
    deps = ""
    for p in files:
        if any(fnmatch.fnmatch(os.path.basename(p), g) for g in DEP_FILES):
            deps += (read_text(os.path.join(ctx["repo"], p)) or "").lower()
    installed = {t for t in LINTERS if t.split("-")[0] in deps}
    # a standalone config for a non-JS tool is its own proof; JS tools need a dependency
    installed |= {t for t in configured if t in ("ruff", "flake8", "pylint", "rubocop", "golangci-lint", "biome") and
                  (t != "biome" or "biome" in deps)}
    orphans = []
    for p in files:
        text = read_text(os.path.join(ctx["repo"], p))
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = DISABLE.search(line)
            if m and m.group(1) not in installed:
                orphans.append(f"{p}:{n} ({m.group(1)})")
    if not configured:
        score = 1
    else:
        score = 5 - (0 if all(t in installed for t in configured) else 1) - (2 if orphans else 0)
    where = ", ".join(orphans[:2]) if orphans else "none"
    return str(score), f"linters configured: {', '.join(configured) or 'none'}; disable comments for a missing tool: {len(orphans)} ({where})"


# 5 -------------------------------------------------------------------------------------------------
def knowledge(ctx):
    decisions = [p for p in ctx["files"] if re.match(r"docs/decisions/[^/]+\.md$", p) and "000-template" not in p]
    agents = os.path.isfile(os.path.join(ctx["repo"], "AGENTS.md"))
    score = min(5, 1 + (1 if agents else 0) + min(len(decisions), 3))
    return str(score), f"{len(decisions)} decision records in docs/decisions/; AGENTS.md {'present' if agents else 'missing'}"


def default_branch(repo):
    """The default branch ref (origin/HEAD, main, master, HEAD), or None when there is none."""
    head = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    for cand in ([head.strip()] if head else []) + ["main", "master", "HEAD"]:
        if git(repo, "rev-parse", "--verify", "-q", cand) is not None:
            return cand
    return None


def shortstat_sizes(out):
    """{sha: changed lines} from `git log --shortstat --format=@<sha>[<TAB>parents]`."""
    sizes, sha = {}, None
    for line in out.splitlines():
        if line.startswith("@"):
            sha = line[1:].split("\t")[0]
            sizes[sha] = 0
        elif sha and "changed" in line:
            sizes[sha] = sum(int(n) for n in re.findall(r"(\d+) (?:insertion|deletion)", line))
    return sizes


def merged_pr_sizes(repo, branch):
    """Size of each merge commit on the first-parent line of `branch`: diff against parent 1."""
    out = git(repo, "log", "--first-parent", "-m", "--shortstat", "--format=@%h%x09%P", branch)
    if not out:
        return {}
    merges = {line[1:].split("\t")[0] for line in out.splitlines()
              if line.startswith("@") and len(line.split("\t")[-1].split()) > 1}
    return {sha: n for sha, n in shortstat_sizes(out).items() if sha in merges}


# 6 -------------------------------------------------------------------------------------------------
def small_changes(ctx):
    """Size per merged PR (first-parent diff vs parent 1) when the default branch has merges, else per commit."""
    repo = ctx["repo"]
    branch = default_branch(repo)
    sizes = merged_pr_sizes(repo, branch) if branch else {}
    unit = "merged PRs"
    if not sizes:
        out = git(repo, "log", "--shortstat", "--format=@%h")
        if not out or "@" not in out:
            return "n/a", "no git history to measure"
        sizes, unit = shortstat_sizes(out), "commits"
    big = {s: n for s, n in sizes.items() if n > BIG_COMMIT}
    if not big:
        return "5", f"0 of {len(sizes)} {unit} above {BIG_COMMIT} changed lines"
    sha, lines = max(big.items(), key=lambda kv: kv[1])
    score = min(4, score_from_share(1 - len(big) / len(sizes)))
    return str(score), f"{len(big)} of {len(sizes)} {unit} above {BIG_COMMIT} changed lines; largest {sha} ({lines} lines)"


# 7 -------------------------------------------------------------------------------------------------
def ci(ctx):
    flows = [p for p in ctx["files"] if re.match(r"\.github/workflows/[^/]+\.ya?ml$", p)]
    if not flows:
        return "1", "no .github/workflows/*"
    tests = e2e = None
    for p in flows:
        for n, line in enumerate((read_text(os.path.join(ctx["repo"], p)) or "").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if not tests and re.search(r"\b(pytest|unittest|jest|vitest|npm (run )?test|go test|cargo test|rspec|mvn test)\b", line):
                tests = f"{p}:{n}"
            if not e2e and re.search(r"e2e|playwright|cypress|end-to-end", line, re.I):
                e2e = f"{p}:{n}"
    score = 5 if tests and e2e else 4 if tests else 3 if e2e else 2
    return str(score), f"{len(flows)} workflows; tests: {tests or 'not found'}; e2e: {e2e or 'not found'}"


# 8 -------------------------------------------------------------------------------------------------
def human_gate(ctx):
    repo = ctx["repo"]
    branch = default_branch(repo)
    out = git(repo, "log", "--first-parent", "--format=%s%x09%P", branch) if branch else None
    if not out:
        return "n/a", "no git history on a default branch"
    via_pr = other = 0
    for line in out.splitlines():
        subject = line.split("\t")[0]
        if subject.startswith("Merge pull request") or re.search(r"\(#\d+\)$", subject):
            via_pr += 1
        else:
            other += 1
    total = via_pr + other
    return str(score_from_share(via_pr / total)), f"{via_pr} of {total} first-parent commits on {branch} came through a PR; {other} did not"


def audit(repo, today, projects_dir, dev_root):
    ctx = {"repo": repo, "names": repo_names(repo), "today": today, "projects_dir": projects_dir,
           "dev_root": dev_root, "files": list_files(repo)}
    rule_score, rule_evidence, expired, invalid = enforced_rules(ctx)
    results = [review(ctx), tests_intent(ctx), (rule_score, rule_evidence), static_checks(ctx), knowledge(ctx),
               small_changes(ctx), ci(ctx), human_gate(ctx)]
    return results, expired, invalid


def default_dev_root():
    """env AI_AUDIT_DEV_ROOT, else the layers' dev_root (home when no layer sets one)."""
    if os.environ.get("AI_AUDIT_DEV_ROOT"):
        return os.environ["AI_AUDIT_DEV_ROOT"]
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "guard"))
        import guard, layers
        given = os.environ.get("AI_SETUP_POLICY")
        if given:
            with open(given) as f:
                return layers.dev_root(json.load(f))
        return layers.dev_root(guard.load())
    except Exception:
        return "~"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score a repo against 8 generic practices (read-only, stdout only).")
    ap.add_argument("repo")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, default: today")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--dev-root", default=default_dev_root(),
                    help="folder with reviews/ and handoffs/ (env AI_AUDIT_DEV_ROOT, default: the layers' dev_root, else ~)")
    args = ap.parse_args(argv)
    repo = os.path.realpath(os.path.expanduser(args.repo))
    if not os.path.isdir(repo):
        print(f"not a directory: {args.repo}", file=sys.stderr)
        return 2
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    except ValueError:
        print(f"bad --today: {args.today} (use YYYY-MM-DD)", file=sys.stderr)
        return 2
    results, expired, invalid = audit(repo, today, os.path.expanduser(args.projects_dir), os.path.expanduser(args.dev_root))
    print(f"ai-audit: {repo} (today {today.isoformat()}). Scores are heuristics 1-5, not a grade.\n")
    print("# | Practice | Score | Evidence")
    for i, (name, (score, evidence)) in enumerate(zip(PRACTICES, results), 1):
        print(f"{i} | {name} | {score} | {evidence.replace('|', '/')}")
    if expired or invalid:
        print()
        for n, text in expired:
            print(f"expired: test it or delete it - AGENTS.md:{n}: {text}")
        for n, text in invalid:
            print(f"invalid date: AGENTS.md:{n}: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
