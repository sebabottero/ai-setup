#!/usr/bin/env python3
"""Encrypted backup of everything personal that is not in a repo and that install.sh does not regenerate.

  backup.sh --full DEST [--dry-run]      -> DEST/ai-personal-YYYYMMDD.tar.age + DEST/RESTORE.md
  backup.sh --restore FILE.age [--home DIR] [--force]

Only the allowlist below is read. Secrets are never opened: they are only listed as "copy by hand".
"""
import argparse
import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "core", "guard"))
import layers

# The generic part. A layer adds its own folders in its policy.json:
#   "backup": {"include": [...], "exclude": [...], "by_hand": [["path", "why"], ...]}
# Paths are relative to $HOME, {{DEV}} is the layers' dev_root. A path with "*" is a glob.
INCLUDE = [
    "{{DEV}}/handoffs",
    "{{DEV}}/ai-notes",
    ".claude/projects/*/memory",
    ".claude/history.jsonl",
    ".gitconfig",
    ".zprofile",
    ".zshenv",
    ".config/git",
    ".config/opencode",
    ".config/anthropic",
]
# Folders left out of an included folder (relative to $HOME); a layer adds more
EXCLUDE = set()
SKIP_NAMES = {".DS_Store", "__pycache__"}
# Listed, never opened
BY_HAND = [
    (".ssh", "SSH keys"),
    (".aws", "AWS credentials"),
    (".microsoft/usersecrets", ".NET user-secrets"),
    (".claude.json", "Claude account, MCP config (run `claude mcp add` again)"),
    (".zsh_history", "may hold pasted secrets"),
    (".config/gh", "GitHub token (run `gh auth login`)"),
    (".claude/projects", "session transcripts (only memory/ is in the backup)"),
]
BY_HAND_PATTERNS = ["every .env.local", "every appsettings.*.local.json"]
SPECIAL = {"MANIFEST", "RESTORE.md"}


def home_dir():
    return os.path.expanduser("~")


def load_policy():
    """The composed policy of the installed layers. AI_SETUP_POLICY points at another file (tests)."""
    try:
        given = os.environ.get("AI_SETUP_POLICY")
        if given:
            with open(given) as f:
                return json.load(f)
        import guard
        return guard.load()
    except (OSError, ValueError):
        return {}


def dev_dir(home, policy):
    """The layers' dev_root as an absolute path under `home` (home itself when no layer sets one)."""
    dev = layers.dev_root(policy)
    return home + dev[1:] if dev.startswith("~") else dev


def rel_path(text, home, policy):
    """A policy path as relative to $HOME, with {{DEV}} expanded."""
    if "{{DEV}}" in text:
        return os.path.relpath(text.replace("{{DEV}}", dev_dir(home, policy)), home)
    return text.strip("/")


def listed(policy, key):
    given = policy.get("backup", {}).get(key, []) if isinstance(policy.get("backup"), dict) else []
    return given if isinstance(given, list) else []


def includes(home, policy):
    # the generic {{DEV}} folders only count when a layer sets a dev_root; otherwise they would resolve to ~/handoffs
    core = [p for p in INCLUDE if "{{DEV}}" not in p or "dev_root" in policy]
    return list(dict.fromkeys(rel_path(p, home, policy) for p in core + [p for p in listed(policy, "include") if isinstance(p, str)]))


def excludes(home, policy):
    return {rel_path(p, home, policy) for p in EXCLUDE | {p for p in listed(policy, "exclude") if isinstance(p, str)}}


def by_hand_items(home, policy):
    """(path, why) the user has to copy by hand, that exist: the generic ones plus the layers'."""
    extra = [tuple(x) for x in listed(policy, "by_hand") if isinstance(x, (list, tuple)) and len(x) == 2]
    return [(rel_path(p, home, policy), why) for p, why in BY_HAND + extra if os.path.lexists(os.path.join(home, rel_path(p, home, policy)))]


def expand(home, policy=None):
    """Files to back up as (absolute, relative, include pattern), plus skipped symlinks."""
    policy = load_policy() if policy is None else policy
    files, skipped = [], []
    skip = excludes(home, policy)

    def add(path, pattern):
        rel = os.path.relpath(path, home)
        if os.path.islink(path):
            skipped.append(rel)
        elif os.path.isfile(path):
            files.append((path, rel, pattern))

    for pattern in includes(home, policy):
        for root in sorted(glob.glob(os.path.join(home, pattern))):
            if os.path.isfile(root) or os.path.islink(root):
                add(root, pattern)
                continue
            for dirpath, dirs, names in os.walk(root):
                reldir = os.path.relpath(dirpath, home)
                dirs[:] = sorted(d for d in dirs if d not in SKIP_NAMES and os.path.join(reldir, d) not in skip)
                for n in sorted(names):
                    if n not in SKIP_NAMES:
                        add(os.path.join(dirpath, n), pattern)
    return files, skipped


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def repo_warnings(home, policy=None):
    """Dirty repos and branches that are not pushed. Warns, never blocks."""
    out = []
    for repo in sorted(glob.glob(os.path.join(dev_dir(home, load_policy() if policy is None else policy), "repos", "*"))):
        if not os.path.exists(os.path.join(repo, ".git")):
            continue
        name = os.path.basename(repo)
        if git(repo, "status", "--porcelain").strip():
            out.append(f"{name}: uncommitted changes")
        for line in git(repo, "for-each-ref", "--format=%(refname:short)|%(upstream:short)|%(upstream:track)", "refs/heads").splitlines():
            branch, upstream, track = (line.split("|") + ["", ""])[:3]
            if not upstream:
                out.append(f"{name}: branch {branch} has no upstream (not pushed)")
            elif "ahead" in track:
                out.append(f"{name}: branch {branch} {track} (unpushed commits)")
    return out


def brewfile():
    if not shutil.which("brew"):
        return None
    r = subprocess.run(["brew", "bundle", "dump", "--file=-"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 and r.stdout else None


def restore_md(by_hand, date, dev="~"):
    lines = [
        f"# Restore of the AI setup ({date})",
        "",
        "This file has no secrets. The backup itself (`*.tar.age`) is encrypted with a passphrase.",
        "",
        "## Steps",
        "1. Install Homebrew, then `brew install age git`.",
        f"2. Clone the engine and your layers: `git clone https://github.com/sebabottero/ai-setup.git {dev}/repos/ai-setup` and the same for each layer you keep outside it.",
        f"3. Restore: `{dev}/repos/ai-setup/backup.sh --restore <this folder>/ai-personal-*.tar.age` (use `--home DIR` to try it first; it never overwrites, `--force` keeps a `.bak`).",
        "4. `brew bundle --file ~/Brewfile`",
        f"5. `{dev}/repos/ai-setup/install.sh`",
        "6. `gh auth login` and `claude mcp add ...` again (restart the session after).",
        "",
        "## Copy by hand (not in the backup)",
    ]
    lines += [f"- `~/{p}`: {why}" for p, why in by_hand]
    lines += [f"- {p}" for p in BY_HAND_PATTERNS]
    return "\n".join(lines) + "\n"


def add_bytes(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = int(time.time())
    tar.addfile(info, io.BytesIO(data))


def full(args):
    home = home_dir()
    policy = load_policy()
    files, skipped = expand(home, policy)
    total = sum(os.path.getsize(p) for p, _, _ in files)
    by_hand = by_hand_items(home, policy)
    warnings = repo_warnings(home, policy)
    date = time.strftime("%Y%m%d")

    print(f"IN ({len(files)} files, {human(total)}):")
    for pattern in includes(home, policy):
        mine = [p for p, _, pat in files if pat == pattern]
        if mine:
            print(f"  ~/{pattern}  {len(mine)} files, {human(sum(os.path.getsize(p) for p in mine))}")
    print("  Brewfile (generated with `brew bundle dump`)" if shutil.which("brew") else "  Brewfile: skipped, brew not found")
    if skipped:
        print("  symlinks skipped: " + ", ".join(skipped))
    print("NOT IN (copy by hand):")
    for p, why in by_hand:
        print(f"  ~/{p}  ({why})")
    for p in BY_HAND_PATTERNS:
        print(f"  {p}")
    print("REPO WARNINGS:" if warnings else "REPO WARNINGS: none")
    for w in warnings:
        print(f"  {w}")
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    if not shutil.which("age"):
        print("age is not installed: brew install age", file=sys.stderr)
        return 1
    dest = os.path.abspath(args.full)
    os.makedirs(dest, exist_ok=True)
    out = os.path.join(dest, f"ai-personal-{date}.tar.age")
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "backup.tar")
        with tarfile.open(plain, "w") as tar:
            for path, rel, _ in files:
                tar.add(path, arcname=rel, recursive=False)
            brew = brewfile()
            if brew:
                add_bytes(tar, "Brewfile", brew.encode())
            doc = restore_md(by_hand, date, layers.dev_root(policy))
            add_bytes(tar, "RESTORE.md", doc.encode())
            names = [r for _, r, _ in files] + (["Brewfile"] if brew else [])
            add_bytes(tar, "MANIFEST", ("\n".join(names) + "\n").encode())
        with tarfile.open(plain) as tar:  # the tar itself reads back
            if len(tar.getnames()) != len(names) + 2:
                print("The tar does not match what was listed", file=sys.stderr)
                return 1
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run(["age", "-p", "-o", out, plain])
        if r.returncode != 0:
            print("age failed; nothing was saved", file=sys.stderr)
            return 1
    with open(out, "rb") as f:
        if not f.read(21) == b"age-encryption.org/v1":
            os.remove(out)
            print("The output is not an age file; removed it", file=sys.stderr)
            return 1
    with open(os.path.join(dest, "RESTORE.md"), "w") as f:
        f.write(doc)
    print(f"Saved to {out} ({human(os.path.getsize(out))}, {len(files)} files). RESTORE.md is next to it.")
    return 0


def restore(args):
    if not shutil.which("age"):
        print("age is not installed: brew install age", file=sys.stderr)
        return 1
    home = os.path.abspath(args.home or home_dir())
    done, conflicts = [], []
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "backup.tar")
        if subprocess.run(["age", "-d", "-o", plain, args.restore]).returncode != 0:
            print("Could not decrypt (wrong passphrase?)", file=sys.stderr)
            return 1
        with tarfile.open(plain) as tar:
            for m in tar.getmembers():
                if m.name in SPECIAL or not m.isfile():
                    continue
                if os.path.isabs(m.name) or ".." in m.name.split("/"):
                    print(f"Skipped unsafe path {m.name}", file=sys.stderr)
                    continue
                target = os.path.join(home, m.name)
                if os.path.lexists(target):
                    if not args.force:
                        conflicts.append(m.name)
                        continue
                    bak = target + ".bak"
                    if os.path.lexists(bak):
                        bak += time.strftime(".%H%M%S")
                    os.rename(target, bak)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.chmod(target, m.mode & 0o777)
                done.append(m.name)
    print(f"Restored {len(done)} files into {home}")
    if conflicts:
        print(f"Conflicts, not overwritten ({len(conflicts)}); use --force to keep a .bak and replace:")
        for c in conflicts:
            print(f"  {c}")
    print("Next: brew bundle --file ~/Brewfile; gh auth login; claude mcp add ...")
    return 0


def main():
    p = argparse.ArgumentParser(prog="backup.sh")
    p.add_argument("--full", metavar="DEST")
    p.add_argument("--restore", metavar="FILE")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--home")
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    if bool(args.full) == bool(args.restore):
        p.error("use exactly one of --full or --restore")
    return full(args) if args.full else restore(args)


if __name__ == "__main__":
    sys.exit(main())
