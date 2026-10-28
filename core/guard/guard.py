#!/usr/bin/env python3
"""Policy guard shared by every tool: decides allow / ask / deny for a shell command or an MCP tool
from build/policy.json (composed from the installed layers). Each adapter only translates its tool's hook format to this one.

  stdin:  {"tool": "bash", "command": "..."}   or   {"tool": "mcp", "name": "server.tool"}
  stdout: {"decision": "allow" | "ask" | "deny", "reason": "..."}   (reason of an ask / deny starts with a risk label)

A regex over shell text is a seatbelt, not a wall: obfuscated commands (base64, string concatenation in a
script) get through. The OS sandbox (Claude: core/policy.json "sandbox") is the wall; this adds the asks the
sandbox cannot express, like "commit needs my OK".
"""
import datetime, fnmatch, json, os, re, shlex, sys

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
WRAPPERS = {"eval", "sudo", "xargs", "env", "time", "nohup", "command", "exec", "nice", "timeout", "builtin", "bash", "sh", "zsh",
            "do", "then", "else", "elif", "if", "while", "until", "!", "{"}
EXEC_FLAGS = {"-exec", "-execdir", "-ok", "-okdir"}  # find . -exec git push {} \;
TMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "$TMPDIR/", "${TMPDIR}/")
TEA_READ_ONLY = {"list", "ls", "view"}
# a command string inside another: bash -c '...', sh -c "...", eval "..." (judged again, up to MAX_DEPTH levels)
INNER = re.compile(r"""\b(?:ba|z)?sh\s+(?:-[A-Za-z]+\s+)*?-[A-Za-z]*c[A-Za-z]*\s+(["'])(.*?)(?<!\\)\1|\beval\s+(["'])(.*?)(?<!\\)\3""", re.S)
MAX_DEPTH = 3
PIPE_TO_SHELL = re.compile(r"\|\s*(?:sudo\s+)?(?:ba|z)?sh(?:\s+-s)?\s*(?:$|[;&|)])")  # curl ... | sh: runs text nobody read
INLINE_CODE = re.compile(r"\b(?:python3?|node|ruby|perl)\s+(?:(?:-\S+\s+)*-[ce]\b|-?\s*<<)")  # -c / -e, or a heredoc
RUNS_COMMANDS = re.compile(r"subprocess|\bos\.(?:system|popen|exec\w*|spawn\w*)|child_process|execSync|spawnSync|\bsystem\(|\bpopen\(|\bexec\(")
# risk shown at the start of every ask / deny reason, by the rule that decided; a rule not listed is medium.
# The guard only labels what it asks about, so there is no low: an allowed command carries no label.
HIGH_RISK = {"secret", "secret-glob", "protected_paths", "pipe-to-shell", "rm-outside-tmp", "git push *", "git push --force*",
             "git push -f*", "git reset --hard*", "git clean *", "git rebase *", "git restore *", "git checkout -- *",
             "git branch -D *", "git stash drop*", "git stash clear*", "git worktree remove*", "git update-ref*",
             "git commit-tree*", "rm -rf *", "rm -fr *", "gh pr merge*", "gh release create*"}


def risk_of(decision, rule):
    return "high" if decision == "deny" or rule in HIGH_RISK else "medium"


def labelled(decision, reason, rule):
    """'🔴 high risk: ...' / '🟡 medium risk: ...' in front of the reason of an ask or deny."""
    if decision == "allow":
        return reason
    risk = risk_of(decision, rule)
    return f"{'🔴' if risk == 'high' else '🟡'} {risk} risk: {reason}"


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


def secret_after_cd(command, policy, cwd=None):
    """cd somewhere, then a relative name: judge the name from the folder the shell would be in (cd ~ && cat .ssh/x)."""
    cur = None
    for part in re.split(r"&&|\|\||[;\n]", command):
        words = words_of(part)
        if words[:1] == ["cd"]:
            target = os.path.expanduser(normalize(words[1]) if len(words) > 1 else "~")
            cur = os.path.normpath(target if target.startswith("/") else os.path.join(cur or cwd or os.getcwd(), target))
            continue
        for word in tokens(part) if cur else ():
            if not word.startswith(("/", "~", "-", "$")):
                hit = secret(os.path.join(cur, word), policy)
                if hit:
                    return hit
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


def bash(command, policy, cwd=None, depth=0):
    """(decision, reason, rule): rule names what decided (a policy pattern or a check), never the command."""
    hit = secret(command, policy) or secret_after_cd(command, policy, cwd)
    if hit and hit[0] == "deny":
        return "deny", f"'{hit[1]}' is a secret (policy: deny_files / deny_home_dirs)", "secret"
    if hit:
        return "ask", f"'{hit[1]}' could expand to a secret file: confirm", "secret-glob"
    target = protected(command, policy, cwd)
    if target:
        return "ask", f"'{target}' is one of the setup's own rules (policy: protected_paths): confirm the change", "protected_paths"
    found = []  # every ask the command earns; the riskiest one is shown, so 'git commit && git reset --hard' reads as high
    if depth < MAX_DEPTH:  # bash -c 'cd repo && git push': judge the inner command as if it was typed alone
        for m in INNER.finditer(command):
            result = bash(m.group(2) if m.group(1) else m.group(4), policy, cwd, depth + 1)
            if result[0] != "allow":
                found.append(result)
    if PIPE_TO_SHELL.search(command):
        found.append(("ask", "a pipe into a shell runs text nobody read: confirm", "pipe-to-shell"))
    if INLINE_CODE.search(command) and RUNS_COMMANDS.search(command):
        found.append(("ask", "inline code that starts other commands hides what runs: confirm", "inline-code"))
    if re.search(r"\bgit\b.*\s-c\s+alias\.", command):
        found.append(("ask", "an inline git alias hides the real command: confirm", "git-alias"))
    for seg in segments(command):
        is_rm, outside = rm_outside_tmp(seg)
        if outside:
            found.append(("ask", f"'rm {outside}' deletes outside tmp: confirm", "rm-outside-tmp"))
            continue
        if is_rm or tea_read_only(seg):  # rm inside tmp, tea list/view: nothing to confirm
            continue
        for pattern in policy["ask_commands"]:
            if fnmatch.fnmatchcase(seg, pattern) or fnmatch.fnmatchcase(seg, pattern.rstrip(" *")):
                found.append(("ask", f"'{seg}' needs your explicit OK (policy: {pattern})", pattern))
                break
    if found:
        return max(found, key=lambda r: risk_of(r[0], r[2]) == "high")  # max keeps the first of equals
    return "allow", "", "-"


def judge(event, policy):
    if event.get("tool") == "bash":
        return bash(event.get("command", ""), policy, event.get("cwd"))
    for pattern in policy["ask_mcp_tools"] if event.get("tool") == "mcp" else ():
        if fnmatch.fnmatchcase(event.get("name", ""), pattern):
            return "ask", f"{event['name']} changes shared data: needs your explicit OK", pattern
    return "allow", "", "-"


def log_decision(tool, decision, rule):
    """One line per decision in AI_SETUP_GUARD_LOG (default ~/.ai-setup/guard.log; "off" disables): time, tool, decision, rule.
    The command is never written, it may hold a secret. A log that cannot be written must not change the decision."""
    path = os.environ.get("AI_SETUP_GUARD_LOG") or os.path.expanduser("~/.ai-setup/guard.log")
    if path == "off":
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:  # keep one previous file, not an endless log
            os.replace(path, path + ".1")
        with open(path, "a") as f:
            f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"), tool, decision, rule]) + "\n")
    except OSError:
        pass


def decide(event, policy=None, log=False):
    """(decision, reason). log=True is for the adapters that answer a real agent; tests and callers stay quiet."""
    decision, reason, rule = judge(event, policy or load())
    reason = labelled(decision, reason, rule)
    if log:
        log_decision(event.get("tool", "?"), decision, rule)
    return decision, reason


def main():
    try:
        decision, reason = decide(json.load(sys.stdin), log=True)
    except Exception as exc:  # a broken guard must not silently allow: ask instead
        decision, reason = "ask", f"policy guard failed ({exc}); confirm manually"
    print(json.dumps({"decision": decision, "reason": reason}))


if __name__ == "__main__":
    main()
