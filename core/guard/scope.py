#!/usr/bin/env python3
"""Scoped approvals for protected paths inside a ticket worktree (<dev root>/worktrees/<repo>/<ticket>/). Used by the Claude
hook adapters/claude/hooks/scoped_edit.py (Edit | Write | MultiEdit | NotebookEdit); the Bash guard does not see those tools.

Inside such a worktree of the setup's own repo, for a path that policy `protected_paths` covers (the same globs, read from the
worktree root instead of the main checkout):
  * exactly one of the paths in this worktree's scope file, and a grant exists  -> allow
  * exactly one of them, no grant yet                                            -> ask (the answer yes creates the grant)
  * any other protected path, a `..` path, a symlink that leaves the worktree    -> ask, every time
Anything else (outside the worktree, a path that is not protected, another repo's worktree): no opinion, the normal pipeline decides.

The scope file (`<scopes dir>/<hash of the worktree>.json`, exact relative paths, no globs) lives outside the worktree, where the
sandbox does not let a Bash command write; it is created only by this script's `add`, which the guard asks about. A grant
(`<hash>.grants.json`) is written by the PostToolUse hook, only for an ask this hook raised (a pending marker per tool_use_id).
AI_SETUP_SCOPES_DIR overrides ~/.ai-setup/scopes ("off" disables scopes); AI_SETUP_WORKTREES overrides <dev root>/worktrees.

  python3 -I scope.py add <worktree> <relative path>...   exact paths of the ticket's allowlist that are protected
  python3 -I scope.py show <worktree>
  python3 -I scope.py clear <worktree>"""
import fnmatch, hashlib, json, os, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
FIELDS = ("file_path", "notebook_path", "path")  # Edit / Write / MultiEdit, NotebookEdit
STALE = 24 * 3600  # a pending marker older than this is ignored
HOOK = "scoped_edit.py"
EVENTS = ("PreToolUse", "PostToolUse")


def scopes_dir():
    path = os.environ.get("AI_SETUP_SCOPES_DIR") or os.path.expanduser("~/.ai-setup/scopes")
    return None if path == "off" else path


def _hash(worktree):
    return hashlib.sha256(worktree.encode()).hexdigest()[:24]


def scope_file(worktree):
    return os.path.join(scopes_dir(), _hash(worktree) + ".json")


def grants_file(worktree):
    return os.path.join(scopes_dir(), _hash(worktree) + ".grants.json")


def _pending_file(tool_use_id):
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(tool_use_id))
    return os.path.join(scopes_dir(), "pending", name + ".json")


def _read(path, worktree):
    """The JSON object in `path` if it names this worktree, else {}: a copied, corrupt or foreign file grants nothing."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("worktree") == worktree else {}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def read_scope(worktree):
    if not scopes_dir():
        return set()
    paths = _read(scope_file(worktree), worktree).get("paths")
    return {p for p in paths if isinstance(p, str)} if isinstance(paths, list) else set()


def _granted(worktree):
    grants = _read(grants_file(worktree), worktree).get("paths")
    return grants if isinstance(grants, dict) else {}


# ---------------------------------------------------------------- where the worktrees are
def bases(policy):
    """(lexical, real) <dev root>/worktrees."""
    raw = os.environ.get("AI_SETUP_WORKTREES") or os.path.join(policy.get("dev_root", "~").rstrip("/") or "~", "worktrees")
    lexical = os.path.normpath(os.path.expanduser(raw))
    return lexical, os.path.realpath(lexical)


def split(path, base):
    """(repo, ticket, rest) for a path under <base>/<repo>/<ticket>/..., else None. `rest` is [] for the worktree itself."""
    rel = os.path.relpath(path, base).split(os.sep)
    if rel[0] == ".." or len(rel) < 2:
        return None
    return rel[0], rel[1], rel[2:]


def worktree_of(path, base):
    """<base>/<repo>/<ticket> when `path` is a file or folder inside it (not the worktree folder itself), else None."""
    found = split(path, base)
    return os.path.join(base, found[0], found[1]) if found and found[2] else None


def relative_globs(policy):
    """Policy protected_paths that start at the setup's root, as lower-case globs relative to a worktree of it."""
    return [p[len("{{AI_SETUP}}/"):].lower() for p in policy.get("protected_paths", []) if p.startswith("{{AI_SETUP}}/")]


def _target(event):
    given = event.get("tool_input")
    given = given if isinstance(given, dict) else {}
    return next((v for f in FIELDS for v in [given.get(f)] if isinstance(v, str) and v), None)


def _inside(path, folder):
    return path == folder or path.startswith(folder.rstrip("/") + "/")


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
    folder = scopes_dir()
    if folder and any(_inside(p, f) for p in (lexical, real) for f in (os.path.normpath(folder), os.path.realpath(folder))):
        return "ask", "scope and grant files are written only by scope.py (which asks), never by an edit: confirm"
    base_lexical, base_real = bases(policy)
    inside_lexical = worktree_of(lexical, base_lexical) or worktree_of(lexical, base_real)
    inside_real = worktree_of(real, base_real)
    if not inside_lexical and not inside_real:
        return None
    if inside_lexical and inside_real != os.path.realpath(inside_lexical):
        return "ask", f"'{raw}' leaves its ticket worktree (a '..' or a symlink): confirm"
    worktree = inside_real
    if split(worktree, base_real)[0] != os.path.basename(ROOT):
        return None  # another repo: the setup's protected paths are not its files
    rel = os.path.relpath(real, worktree)
    if not any(fnmatch.fnmatchcase(rel.lower(), g) for g in relative_globs(policy)):
        return None
    why = f"'{rel}' is one of the setup's own rules (policy: protected_paths)"
    if ".." in raw.replace("\\", "/").split("/") or rel not in read_scope(worktree):
        return "ask", f"{why}: confirm the change (not in this ticket's scope, so it asks every time)"
    if rel in _granted(worktree):
        return "allow", f"{why}: in this ticket's scope and confirmed once"
    if event.get("tool_use_id") and folder:
        try:
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
    worktree, rel = marker.get("worktree"), marker.get("rel")
    if not isinstance(marker, dict) or not isinstance(worktree, str) or not isinstance(rel, str):
        return
    if time.time() - float(marker.get("time", 0)) > STALE or rel not in read_scope(worktree):
        return
    target = _target(event)
    if target:
        cwd = event.get("cwd") or os.getcwd()
        if os.path.realpath(os.path.join(cwd, os.path.expanduser(target))) != os.path.join(worktree, rel):
            return  # the marker is for another path than the one that ran
    grants = _granted(worktree)
    grants[rel] = time.time()
    _write(grants_file(worktree), {"worktree": worktree, "paths": grants})


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
    base = bases(policy)[1]
    found = split(worktree, base)
    if not found or found[2] or not os.path.isdir(worktree):
        raise ValueError(f"{text} is not a ticket worktree (<dev root>/worktrees/<repo>/<ticket>)")
    return worktree


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
    _write(scope_file(worktree), {"worktree": worktree, "paths": merged, "time": time.time()})
    grants = {k: v for k, v in _granted(worktree).items() if k not in clean}  # a new Gate 1: one more ask per path
    _write(grants_file(worktree), {"worktree": worktree, "paths": grants})
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
    except (ValueError, OSError) as exc:
        sys.exit(f"scope.py: {exc}" + ("\nthe sandbox blocks this folder: run the command outside it (a `! ` line)"
                                       if isinstance(exc, PermissionError) else ""))


if __name__ == "__main__":
    main(sys.argv)
