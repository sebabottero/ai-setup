#!/usr/bin/env python3
"""Scoped approvals for protected paths inside a ticket worktree (<dev root>/worktrees/<repo>/<ticket>/). Used by the Claude
hook adapters/claude/hooks/scoped_edit.py (Edit | Write | MultiEdit | NotebookEdit); the Bash guard does not see those tools.

Inside such a worktree of the setup's own repo, for a path that policy `protected_paths` covers (the same globs, read from the
worktree root instead of the main checkout):
  * exactly one of the paths in this worktree's scope file, and a fresh grant exists -> allow
  * exactly one of them, no grant yet                                                  -> ask (the answer yes creates the grant)
  * any other protected path, a `..` path, a symlink that leaves the worktree          -> ask, every time
Anything else (outside the worktree, a path that is not protected, another repo's worktree): no opinion, the normal pipeline decides.
Folder names are compared without case (macOS), so `WORKTREES/AI-SETUP/T1/install.py` is the same file as the real one.
"The setup's own repo" is known by the name of its main checkout (the git common dir), so it holds when install ran from a worktree.

The scope file (`<scopes dir>/<hash of the worktree>.json`, exact relative paths, no globs) lives outside the worktree, where the
sandbox does not let a Bash command write; the owner creates it with `add` (a `! ` line, the guard also asks), and the hook asks about
any edit of the scopes, pending or sessions folder. A scope names the worktree's identity (its .git file), so a worktree recreated
under the same name inherits nothing; it expires after SCOPE_TTL and a grant after GRANT_TTL. A grant (`<hash>.grants.json`) is written by
the PostToolUse hook, only for an ask this hook raised (a pending marker per tool_use_id).
AI_SETUP_SCOPES_DIR overrides ~/.ai-setup/scopes ("off" disables scopes); AI_SETUP_WORKTREES overrides <dev root>/worktrees.

  python3 -I scope.py add <worktree> <relative path>...   exact paths of the ticket's allowlist that are protected
  python3 -I scope.py show <worktree>
  python3 -I scope.py clear <worktree>                    when the worktree is deleted"""
import fnmatch, hashlib, json, os, re, shlex, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
FIELDS = ("file_path", "notebook_path", "path")  # Edit / Write / MultiEdit, NotebookEdit
STALE = 24 * 3600  # a pending marker older than this is ignored and pruned
GRANT_TTL = 12 * 3600  # after this a protected path in scope asks once more
SCOPE_TTL = 72 * 3600  # after this the scope itself is gone (a new Gate 1 writes it again)
HOOK = "scoped_edit.py"
EVENTS = ("PreToolUse", "PostToolUse")


def _fold(text):
    return text.casefold()


def scopes_dir():
    path = os.environ.get("AI_SETUP_SCOPES_DIR") or os.path.expanduser("~/.ai-setup/scopes")
    return None if path == "off" else path


def state_dirs():
    """The folders that hold approval state (scopes, grants, pending markers, session ids): an edit of anything in them asks,
    under the configured path and under the default one."""
    home = os.path.expanduser("~/.ai-setup")
    found = [scopes_dir(), os.environ.get("AI_SETUP_PENDING_DIR"), os.environ.get("AI_SETUP_SESSIONS_DIR")]
    found += [os.path.join(home, d) for d in ("scopes", "pending", "sessions")]
    return [os.path.expanduser(d) for d in found if d and d != "off"]


def _hash(worktree):
    return hashlib.sha256(_fold(worktree).encode()).hexdigest()[:24]


def scope_file(worktree):
    return os.path.join(scopes_dir(), _hash(worktree) + ".json")


def grants_file(worktree):
    return os.path.join(scopes_dir(), _hash(worktree) + ".grants.json")


def _pending_file(tool_use_id):
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(tool_use_id))
    return os.path.join(scopes_dir(), "pending", name + ".json")


def worktree_id(worktree):
    """What tells this worktree from another one created later under the same name: its .git file (written once, by git)."""
    try:
        st = os.stat(os.path.join(worktree, ".git"))
    except OSError:
        return "nogit"
    return f"{st.st_ino}:{st.st_mtime_ns}"


def _read(path, worktree):
    """The JSON object in `path` if it names this worktree (and this incarnation of it), else {}: a copied, corrupt, foreign
    or stale file grants nothing."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    ok = isinstance(data, dict) and isinstance(data.get("worktree"), str) and _fold(data["worktree"]) == _fold(worktree)
    return data if ok and data.get("id") == worktree_id(worktree) else {}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def read_scope(worktree):
    if not scopes_dir():
        return set()
    data = _read(scope_file(worktree), worktree)
    stamp = data.get("time")
    if not isinstance(stamp, (int, float)) or time.time() - stamp > SCOPE_TTL:
        return set()
    paths = data.get("paths")
    return {p for p in paths if isinstance(p, str)} if isinstance(paths, list) else set()


def _granted(worktree):
    """{relative path: time} of the grants that have not expired."""
    grants = _read(grants_file(worktree), worktree).get("paths")
    now = time.time()
    return {k: v for k, v in grants.items() if isinstance(v, (int, float)) and now - v <= GRANT_TTL} if isinstance(grants, dict) else {}


# ---------------------------------------------------------------- which repo, which worktree
def git_repo_name(worktree):
    """Folder name of the main checkout of a linked git worktree (read from its .git file and the common dir), else None."""
    try:
        with open(os.path.join(worktree, ".git")) as f:
            m = re.match(r"gitdir:\s*(.+)", f.read().strip())
        gitdir = os.path.normpath(os.path.join(worktree, m.group(1)))
        with open(os.path.join(gitdir, "commondir")) as f:
            common = os.path.normpath(os.path.join(gitdir, f.read().strip()))
    except (OSError, AttributeError):
        return None
    return os.path.basename(os.path.dirname(common)) if os.path.basename(common) == ".git" else os.path.basename(common)


def repo_identity(root=None):
    """The name of this repo: its main checkout's folder, also when `root` is a linked worktree of it (so not the ticket name)."""
    root = root or ROOT
    return git_repo_name(root) or os.path.basename(root)


def bases(policy):
    """(lexical, real) <dev root>/worktrees."""
    raw = os.environ.get("AI_SETUP_WORKTREES") or os.path.join(policy.get("dev_root", "~").rstrip("/") or "~", "worktrees")
    lexical = os.path.normpath(os.path.expanduser(raw))
    return lexical, os.path.realpath(lexical)


def _parts(path):
    return [p for p in path.split(os.sep) if p]


def split(path, base):
    """(repo, ticket, rest) for a path under <base>/<repo>/<ticket>/..., else None; `base` is matched without case. `rest` is []
    for the worktree itself."""
    p, b = _parts(path), _parts(base)
    if len(p) < len(b) + 2 or [_fold(x) for x in p[:len(b)]] != [_fold(x) for x in b]:
        return None
    return p[len(b)], p[len(b) + 1], p[len(b) + 2:]


def worktree_of(path, base):
    """<base>/<repo>/<ticket> when `path` is a file or folder inside it (not the worktree folder itself), else None."""
    found = split(path, base)
    return os.path.join(base, found[0], found[1]) if found and found[2] else None


def _inside(path, folder):
    p, f = _parts(path), _parts(folder)
    return len(p) >= len(f) and [_fold(x) for x in p[:len(f)]] == [_fold(x) for x in f]


def relative_globs(policy):
    """Policy protected_paths that start at the setup's root, as lower-case globs relative to a worktree of it."""
    return [p[len("{{AI_SETUP}}/"):].lower() for p in policy.get("protected_paths", []) if p.startswith("{{AI_SETUP}}/")]


def _target(event):
    given = event.get("tool_input")
    given = given if isinstance(given, dict) else {}
    return next((v for f in FIELDS for v in [given.get(f)] if isinstance(v, str) and v), None)


def _prune_pending():
    folder = os.path.join(scopes_dir(), "pending")
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        try:
            if time.time() - os.path.getmtime(path) > STALE:
                os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------- the decision
def check(event, policy=None):
    """(decision, reason) for an Edit | Write PreToolUse event, or None for no opinion. May raise: the hook then asks."""
    raw = _target(event)
    if not raw:
        return None
    if policy is None:
        import guard
        policy = guard.load()
    raw = os.path.expanduser(raw)
    path = raw if os.path.isabs(raw) else os.path.join(event.get("cwd") or os.getcwd(), raw)
    lexical, real = os.path.normpath(path), os.path.realpath(path)
    for folder in state_dirs():
        if any(_inside(p, f) for p in (lexical, real) for f in (os.path.normpath(folder), os.path.realpath(folder))):
            return "ask", "scope, grant, pending and session files are written by scope.py and the hooks, never by an edit: confirm"
    base_lexical, base_real = bases(policy)
    inside_lexical = worktree_of(lexical, base_lexical) or worktree_of(lexical, base_real)
    inside_real = worktree_of(real, base_real)
    if not inside_lexical and not inside_real:
        return None
    if inside_lexical and (not inside_real or _fold(inside_real) != _fold(os.path.realpath(inside_lexical))):
        return "ask", f"'{raw}' leaves its ticket worktree (a '..' or a symlink): confirm"
    worktree = inside_real
    identity = _fold(repo_identity())
    if identity not in (_fold(split(worktree, base_real)[0]), _fold(git_repo_name(worktree) or "")):
        return None  # another repo (by folder name and by git common dir): the setup's protected paths are not its files
    rel = "/".join(_parts(real)[len(_parts(worktree)):])
    if not any(fnmatch.fnmatchcase(rel.lower(), g) for g in relative_globs(policy)):
        return None
    why = f"'{rel}' is one of the setup's own rules (policy: protected_paths)"
    if ".." in raw.replace("\\", "/").split("/") or rel not in read_scope(worktree):
        return "ask", f"{why}: confirm the change (not in this ticket's scope, so it asks every time)"
    if rel in _granted(worktree):
        return "allow", f"{why}: in this ticket's scope and confirmed once"
    folder = scopes_dir()
    if event.get("tool_use_id") and folder:
        try:
            _prune_pending()
            _write(_pending_file(event["tool_use_id"]), {"worktree": worktree, "rel": rel, "time": time.time()})
        except OSError:
            pass  # without the marker there is no grant: it only asks again next time
    return "ask", f"{why}: in this ticket's scope, confirm once (later edits of this file in this worktree will not ask)"


def after(event):
    """PostToolUse success of an Edit | Write: turn the pending marker of this tool_use_id into a grant."""
    if not scopes_dir() or not event.get("tool_use_id"):
        return
    path = _pending_file(event["tool_use_id"])
    try:
        with open(path) as f:
            marker = json.load(f)
        os.remove(path)
    except (OSError, ValueError):
        return
    if not isinstance(marker, dict):
        return
    worktree, rel = marker.get("worktree"), marker.get("rel")
    if not isinstance(worktree, str) or not isinstance(rel, str):
        return
    if time.time() - float(marker.get("time", 0)) > STALE or rel not in read_scope(worktree):
        return
    target = _target(event)
    if target:
        cwd = event.get("cwd") or os.getcwd()
        if _fold(os.path.realpath(os.path.join(cwd, os.path.expanduser(target)))) != _fold(os.path.join(worktree, rel)):
            return  # the marker is for another path than the one that ran
    grants = _granted(worktree)
    grants[rel] = time.time()
    _write(grants_file(worktree), {"worktree": worktree, "id": worktree_id(worktree), "paths": grants})


# ---------------------------------------------------------------- installed-hook check
def hook_problem(settings):
    """Why the hook is not wired in this settings.json (a dict), or None. Without it, protected paths in worktrees do not ask."""
    for event in EVENTS:
        groups = (settings.get("hooks") or {}).get(event) or []
        ok = any(HOOK in h.get("command", "") and "Edit" in g.get("matcher", "") and "Write" in g.get("matcher", "")
                 for g in groups for h in g.get("hooks", []))
        if not ok:
            return f"{HOOK} is not registered for {event} on Edit|Write: protected paths in ticket worktrees will not ask (run ./install.sh)"
    return None


# ---------------------------------------------------------------- command line
def worktree_arg(text, policy):
    worktree = os.path.realpath(os.path.expanduser(text))
    found = split(worktree, bases(policy)[1])
    if not found or found[2] or not os.path.isdir(worktree):
        raise ValueError(f"{text} is not a ticket worktree (<dev root>/worktrees/<repo>/<ticket>)")
    return os.path.join(bases(policy)[1], found[0], found[1])


def exact_path(worktree, text):
    """`text` as a clean relative path of a plain file location in the worktree: no glob, no '..', no symlink on the way."""
    if not text or os.path.isabs(text) or ".." in text.split("/") or any(c in text for c in "*?[]\0\\") or text != os.path.normpath(text):
        raise ValueError(f"'{text}' is not an exact relative path (no glob, no '..', not absolute)")
    if os.path.realpath(os.path.join(worktree, text)) != os.path.join(worktree, text):
        raise ValueError(f"'{text}' goes through a symlink: scope the real path")
    return text


def add(worktree, paths, policy=None):
    if policy is None:
        import guard
        policy = guard.load()
    if not scopes_dir():
        raise ValueError("scopes are off (AI_SETUP_SCOPES_DIR=off)")
    worktree = worktree_arg(worktree, policy)
    clean = [exact_path(worktree, p) for p in paths]
    if not clean:
        raise ValueError("no paths given")
    merged = sorted(read_scope(worktree) | set(clean))
    ident = worktree_id(worktree)
    _write(scope_file(worktree), {"worktree": worktree, "id": ident, "paths": merged, "time": time.time()})
    grants = {k: v for k, v in _granted(worktree).items() if k not in clean}  # a new Gate 1: one more ask per path
    _write(grants_file(worktree), {"worktree": worktree, "id": ident, "paths": grants})
    return merged


def clear(worktree, policy=None):
    if policy is None:
        import guard
        policy = guard.load()
    worktree = worktree_arg(worktree, policy)
    for path in (scope_file(worktree), grants_file(worktree)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def main(argv):
    if len(argv) < 3 or argv[1] not in ("add", "show", "clear"):
        sys.exit("usage: scope.py add <worktree> <path>... | show <worktree> | clear <worktree>")
    try:
        if argv[1] == "add":
            print("\n".join(add(argv[2], argv[3:])))
        elif argv[1] == "clear":
            clear(argv[2])
        else:
            import guard
            print("\n".join(sorted(read_scope(worktree_arg(argv[2], guard.load())))))
    except PermissionError as exc:
        # the sandbox cannot write the scopes folder, by design: the owner runs the same command outside it
        sys.exit(f"scope.py: {exc}\nrun it yourself, outside the sandbox:\n! "
                 + shlex.join(["python3", "-I", os.path.realpath(__file__)] + argv[1:]))
    except (ValueError, OSError) as exc:
        sys.exit(f"scope.py: {exc}")


if __name__ == "__main__":
    main(sys.argv)
