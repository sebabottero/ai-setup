#!/usr/bin/env python3
"""Policy guard shared by every tool: decides allow / ask / deny for a shell command or an MCP tool
from build/policy.json (composed from the installed layers). Each adapter only translates its tool's hook format to this one.

  stdin:  {"tool": "bash", "command": "..."}   or   {"tool": "mcp", "name": "server.tool"}
  stdout: {"decision": "allow" | "ask" | "deny", "reason": "..."}

A regex over shell text is a seatbelt, not a wall: obfuscated commands (base64, string concatenation in a
script) get through. The OS sandbox (Claude: core/policy.json "sandbox") is the wall; this adds the asks the
sandbox cannot express, like "commit needs my OK".
"""
import fnmatch, json, os, re, shlex, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
POLICY = os.path.join(ROOT, "build", "policy.json")  # composed by install.py from the installed layers
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import layers
GLOB = re.compile(r"[*?\[]")
# git options that come before the subcommand; the first group takes a separate value
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
# a write to a protected path: redirection, in-place edits, file moves, or code run inline
WRITES = re.compile(r"(?<![-=])>(?!=)|\bsed\b[^|;&]*\s-i|\btee\b|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bchmod\b|\bln\b|\bperl\b|"
                    r"\b(python3?|node|ruby)\s+(-\S+\s+)*-[ce]\b|\bgit\s+(checkout|restore|apply|stash)\b")
NO_OUTPUT = re.compile(r"\d*>&\d+|\d*>>?\s*/dev/(null|stderr|stdout)")  # 2>&1, >/dev/null: not a file write
# words that may come before the real command: wrappers (sudo git push), shell keywords, and their flags
WRAPPERS = {"sudo", "xargs", "env", "time", "nohup", "command", "exec", "nice", "timeout", "builtin", "bash", "sh", "zsh",
            "do", "then", "else", "elif", "if", "while", "until", "!", "{"}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}  # find . -exec git push {} \;
TMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "$TMPDIR/", "${TMPDIR}/")
TEA_READ_ONLY = {"list", "ls", "view"}


def load():
    """build/policy.json; before the first install, every layer present (the strictest choice)."""
    if os.path.isfile(POLICY):
        with open(POLICY) as f:
            return json.load(f)
    return layers.compose_policy(ROOT, layers.present(ROOT))


def words_of(part):
    part = re.sub(r"[`()]", " ", part)
    try:
        return shlex.split(part)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        return re.sub(r"[\"']", " ", part).split()


def starts_command(words, i):
    return i == 0 or words[i - 1] in EXEC_FLAGS or all(
        w in WRAPPERS or w.startswith("-") or re.fullmatch(r"\d+[smhd]?", w) for w in words[:i])


def rm_outside_tmp(seg):
    """(True, first target outside tmp or None) for an rm / rmdir / find -delete segment; (False, None) otherwise."""
    words = seg.split()
    cmd = os.path.basename(words[0]) if words else ""
    if cmd in ("rm", "rmdir"):
        targets = [w for w in words[1:] if not w.startswith("-")]
    elif cmd == "find" and "-delete" in words:
        paths = []  # find [-H|-L|-P] path... expression: the paths end at the first expression word
        for w in words[1:]:
            if w in ("-H", "-L", "-P"):
                continue
            if w.startswith(("-", "(", "!")):
                break
            paths.append(w)
        targets = paths or ["."]
    else:
        return False, None
    prefixes = TMP_PREFIXES + ((os.environ["TMPDIR"].rstrip("/") + "/",) if os.environ.get("TMPDIR") else ())
    for target in targets:
        inside = any(target.startswith(p) and len(target) > len(p) for p in prefixes)
        if not inside or ".." in target.split("/"):
            return True, target
    return True, None


def tea_read_only(seg):
    words = seg.split()
    return words[:1] == ["tea"] and (words[1:2] in (["--version"], ["--help"], ["whoami"]) or words[2:3] in
                                     [[v] for v in TEA_READ_ONLY])


def segments(command):
    # one entry per simple command: split on ; && || | newlines, drop subshell parens and env assignments
    for part in re.split(r"&&|\|\||[;|\n]", command):
        words = [w for w in words_of(part) if not re.match(r"^\w+=", w)]
        # the real command is the first word, or follows wrappers: sudo git push, xargs git push, bash -c "git push"
        # (a "git push" that is only an argument, like echo "git push", is text and does not count)
        for i in range(len(words)):
            if not starts_command(words, i):
                continue
            yield " ".join(words[i:])
            if words[i] == "git":  # git --no-pager -C dir -c k=v push → git push
                j = i + 1
                while j < len(words) and words[j].startswith("-"):
                    j += 2 if words[j] in GIT_OPTS_WITH_VALUE else 1
                if j > i + 1:
                    yield " ".join(["git"] + words[j:])


def normalize(command):
    home = os.path.expanduser("~")
    command = re.sub(r"[\"']?\$\{?HOME\}?[\"']?", "~", command)
    return command.replace(home, "~")


def tokens(command):
    for word in re.split(r"[\s\"'`=<>|;&()]+", normalize(command)):
        word = word.lstrip("@")  # curl -d @file
        if word:
            yield word


def glob_hits_secret_file(name, policy):
    """A glob that matches a secret file name and also spells part of it (.env*, *.local.json); a bare * or .* does not."""
    concrete = [f.replace("*", "x") for f in policy["deny_files"]]
    chunks = [c for c in re.split(r"[*?\[\]]+", name) if c]
    return sum(map(len, chunks)) >= 3 and any(
        fnmatch.fnmatchcase(f, name) and all(c in f for c in chunks) for f in concrete)


def secret(command, policy):
    """('deny', word) for a secret named outright, ('ask', word) for a glob that could expand to one."""
    for word in tokens(command):
        name = os.path.basename(word)
        if any(fnmatch.fnmatchcase(name, f) for f in policy["deny_files"]):
            return "deny", word
        if any(word == d or word.startswith(d + "/") for d in policy["deny_home_dirs"]):
            return "deny", word
        if GLOB.search(word) and not re.fullmatch(r"\*\.\w+", name):  # *.json alone is too common to ask
            if (glob_hits_secret_file(name, policy) or word.startswith("~") and
                    any(fnmatch.fnmatchcase(d, "/".join(word.split("/")[:d.count("/") + 1]))
                        for d in policy["deny_home_dirs"])):
                return "ask", word
    return None


def protected(command, policy, cwd=None):
    """A protected path (the setup's own rules) that the command looks like it writes to."""
    if not WRITES.search(NO_OUTPUT.sub("", command)):
        return None
    home = os.path.expanduser("~")
    cwd = cwd or os.getcwd()
    patterns = [p.replace("{{AI_SETUP}}", ROOT).replace("~", home, 1) for p in policy.get("protected_paths", [])]
    in_setup = cwd == ROOT or cwd.startswith(ROOT + "/")
    # a relative path only counts inside ai-setup (cwd there, or the command names the folder): not any ./tests
    relative = ["*" + os.path.relpath(p, ROOT) for p in patterns if p.startswith(ROOT + "/")] \
        if not in_setup and os.path.basename(ROOT) in command else []
    for word in tokens(command):
        full = os.path.expanduser(word)
        if in_setup and not os.path.isabs(full):
            full = os.path.normpath(os.path.join(cwd, full))
        for candidate in (full, full.rstrip("/") + "/x"):
            if any(fnmatch.fnmatchcase(candidate, p) for p in patterns + relative):
                return word
    return None


def bash(command, policy, cwd=None):
    hit = secret(command, policy)
    if hit and hit[0] == "deny":
        return "deny", f"'{hit[1]}' is a secret (policy: deny_files / deny_home_dirs)"
    if hit:
        return "ask", f"'{hit[1]}' could expand to a secret file: confirm"
    target = protected(command, policy, cwd)
    if target:
        return "ask", f"'{target}' is one of the setup's own rules (policy: protected_paths): confirm the change"
    if re.search(r"\bgit\b.*\s-c\s+alias\.", command):
        return "ask", "an inline git alias hides the real command: confirm"
    for seg in segments(command):
        is_rm, outside = rm_outside_tmp(seg)
        if outside:
            return "ask", f"'rm {outside}' deletes outside tmp: confirm"
        if is_rm or tea_read_only(seg):  # rm inside tmp, tea list/view: nothing to confirm
            continue
        for pattern in policy["ask_commands"]:
            if fnmatch.fnmatchcase(seg, pattern) or fnmatch.fnmatchcase(seg, pattern.rstrip(" *")):
                return "ask", f"'{seg}' needs your explicit OK (policy: {pattern})"
    return "allow", ""


def decide(event, policy=None):
    policy = policy or load()
    if event.get("tool") == "bash":
        return bash(event.get("command", ""), policy, event.get("cwd"))
    if event.get("tool") == "mcp" and any(fnmatch.fnmatchcase(event.get("name", ""), p) for p in policy["ask_mcp_tools"]):
        return "ask", f"{event['name']} changes shared data: needs your explicit OK"
    return "allow", ""


def main():
    try:
        decision, reason = decide(json.load(sys.stdin))
    except Exception as exc:  # a broken guard must not silently allow: ask instead
        decision, reason = "ask", f"policy guard failed ({exc}); confirm manually"
    print(json.dumps({"decision": decision, "reason": reason}))


if __name__ == "__main__":
    main()
