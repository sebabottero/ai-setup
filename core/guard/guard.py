#!/usr/bin/env python3
"""Policy guard shared by every tool: decides allow / ask / deny for a shell command or an MCP tool
from build/policy.json (composed from the installed layers). Each adapter only translates its tool's hook format to this one.

  stdin:  {"tool": "bash", "command": "...", "unsandboxed": true?}   or   {"tool": "mcp", "name": "server.tool"}
  stdout: {"decision": "allow" | "ask" | "deny", "reason": "..."}   (reason of an ask / deny starts with a risk label)

A regex over shell text is a seatbelt, not a wall: obfuscated commands (base64, string concatenation in a
script) get through. The OS sandbox (Claude: core/policy.json "sandbox") is the wall; this adds the asks the
sandbox cannot express, like "commit needs my OK".
"""
import datetime, fnmatch, json, os, re, shlex, stat, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
POLICY = os.path.join(ROOT, "build", "policy.json")  # composed by install.py from the installed layers
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import layers, review_report
GLOB = re.compile(r"[*?\[]")
# git options that come before the subcommand; the first group takes a separate value
GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--super-prefix"}
# --output (git takes any prefix), rg --pre, or an option name spelled with an escape or a variable (--o\utput, --$O) that hides which one it is
READ_OPTS = re.compile(r"""(?<![\w-])--(?:(?:o(?:u(?:t(?:p(?:u(?:t)?)?)?)?)?|pre)(?=[=\s'"]|$)|[\w-]*[\\$])""")
# a write to a protected path: redirection, in-place edits, file moves, those options, a sed w command, or code run inline
WRITES = re.compile(r"(?<![-=])>(?!=)|\bsed\b[^|;&]*\s-i|\bsed\b[^|&]*[\d$/}'\";{ \\]w[ \t]*[^\s'\"]|\btee\b|\bmv\b|\bcp\b|\brm\b|\btruncate\b|\bchmod\b|\bln\b|\bperl\b|"
                    r"\bgit\s+(checkout|restore|apply|stash)\b|" + READ_OPTS.pattern)
# inline code (python -c, node -e, a heredoc) only counts as a write when the code looks like it writes: reading the
# setup's own rules with json.load(open('core/policy.json')) is not a change
CODE_WRITES = re.compile(r"""open\([^,)]*,\s*['"][rbt]*[wax+][rwabxt+]*['"]|\bmode\s*=\s*['"][rbt]*[wax+]|\.write(?:_text|_bytes|lines)?\(|"""
                         r"""\bjson\.dump\(|\bos\.(?:remove|unlink|rename|replace|rmdir|removedirs|truncate|chmod|symlink|link)\b|"""
                         r"""\bshutil\.|\.unlink\(|\.(?:rename|touch|mkdir|rmdir|symlink_to|chmod)\(|"""
                         r"""\bfs\w*\.(?:write|append|unlink|rm|rename|copy|truncate|chmod|symlink)\w*|\bFile(?:Utils)?\.\w*(?:write|delete|rm|mv|cp)|"""
                         r"""\b(?:write|append|copy)File(?:Sync)?\(|\b(?:unlink|rm|rmdir|rename|truncate|chmod|symlink|mkdir)Sync\(""")
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
HIGH_RISK = {"outside-sandbox", "outside-sandbox-write", "secret", "secret-glob", "protected_paths", "pipe-to-shell", "rm-outside-tmp", "git push *", "git push --force*",
             "git push -f*", "git reset --hard*", "git clean *", "git rebase *", "git restore *", "git checkout -- *",
             "git branch -D *", "git stash drop*", "git stash clear*", "git worktree remove*", "git update-ref*",
             "git commit-tree*", "rm -rf *", "rm -fr *", "gh pr merge*", "gh release create*", "merge-without-review", "merge-unchecked", "review-report-write"}
# merge gate: merging into the default branch needs a review report; these are the policy asks it replaces when it applies
GATE_RULES = ("git merge *", "gh pr merge*")
PULL_VALUE_OPTS = {"-s", "-X", "--strategy", "--strategy-option", "--depth", "--deepen", "--shallow-since", "--shallow-exclude",
                   "--upload-pack", "--negotiation-tip", "--negotiation-restrict", "--negotiation-include", "--refmap", "--server-option", "-o", "-j", "--jobs",
                   "--cleanup"}  # only options whose value is a SEPARATE word: -S / --gpg-sign / --recurse-submodules take it attached
MERGE_VALUE_OPTS = {"-m", "-F", "-s", "-X", "--file", "--message", "--strategy", "--strategy-option", "--into-name", "--cleanup"}
WRAPPER_VALUE_OPTS = {"-C", "--chdir", "-u", "--user", "-g", "--group", "-U", "--unset"}  # env / sudo options that take a value
GH_MERGE_VALUE_OPTS = {"-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit", "-R", "--repo"}
REPORT_TAG = re.compile(r"\[report: [^\]]+\]")


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


def shell_words(part):
    """The words of a simple command as the shell sees them: a quoted word stays one word, even with `(` or a backtick
    in it. Parens and backticks outside quotes are dropped (`(cd x`, `$(rm y`)."""
    part = re.sub(r"""('[^']*'|"(?:\\.|[^"\\])*")|[`()]""", lambda m: m.group(1) or " ", part)
    try:
        return shlex.split(part)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        return re.sub(r"[\"']", " ", part).split()


class Seg(str):
    """One simple command as text (what the ask patterns match), with `words`: the real shell words from the command
    word on, assignments and quotes intact (what `rm` is judged on), and `real`: False for a guess from a split that
    ignored quotes (it can only add an ask)."""
    words = None
    real = True


def starts_command(words, i):
    return i == 0 or words[i - 1] in EXEC_FLAGS or all(
        w in WRAPPERS or w.startswith("-") or re.fullmatch(r"\d+[smhd]?", w) for w in words[:i])


def rm_targets(args):
    """The paths an rm / rmdir names: no options, and after `--` every word (`rm -- -foo` removes a file called -foo)."""
    if "--" in args:
        i = args.index("--")
        return [w for w in args[:i] if not w.startswith("-")] + args[i + 1:]
    return [w for w in args if not w.startswith("-")]


def rm_words(seg):
    """The words of a segment without the redirections that write nowhere (rm -rf x 2>/dev/null: not a target)."""
    if getattr(seg, "words", None) is None:
        return NO_OUTPUT.sub(" ", seg).split()
    words, i = [], 0
    while i < len(seg.words):
        w = seg.words[i]
        if re.fullmatch(r"\d*>&\d+|(?:\d*|&)>>?/dev/(?:null|stderr|stdout)", w):
            i += 1
        elif re.fullmatch(r"(?:\d*|&)>>?", w) and i + 1 < len(seg.words) and re.fullmatch(r"/dev/(?:null|stderr|stdout)", seg.words[i + 1]):
            i += 2
        else:
            words.append(w)
            i += 1
    return words


def xargs_rm(seg):
    """xargs ... rm: the targets come from input nobody read."""
    words = rm_words(seg)
    return bool(words) and os.path.basename(words[0]) == "xargs" and any(os.path.basename(w) in ("rm", "rmdir") for w in words[1:])


def rm_outside_tmp(seg):
    """(True, first target outside tmp or None) for an rm / rmdir / find -delete segment; (False, None) otherwise."""
    words = rm_words(seg)
    cmd = os.path.basename(words[0]) if words else ""
    if cmd in ("rm", "rmdir"):
        targets = rm_targets(words[1:])
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
    for target in targets:
        if not _inside_tmp(target):
            return True, target
    return True, None


def _inside_tmp(target):
    prefixes = TMP_PREFIXES + ((os.environ["TMPDIR"].rstrip("/") + "/",) if os.environ.get("TMPDIR") else ())
    return any(target.startswith(p) and len(target) > len(p) for p in prefixes) and ".." not in target.split("/")


ASSIGN = re.compile(r"""(?:^|[;&|\n]\s*)(?:export\s+)?([A-Za-z_]\w*)=(?:"(%s)"|'(%s)'|(%s))(?=\s*(?:&&|;|\n|$))""" % (r"[\w./~:@%+=, -]+", r"[\w./~:@%+=, -]+", r"[\w./~:@%+=,-]+"))  # plain words only: ; & | newline or redirects in the value would split the pasted text into extra commands
COMPOUND = re.compile(r"\b(?:if|then|else|elif|fi|while|until|for|do|done|case|esac|select|function|readonly|trap|IFS)\b")
UNSAFE_AROUND = re.compile(r"\|\||\||&|[(){}`]|\b(?:eval|source|read|declare|typeset|local|integer|float|private|unset|export|exec|printf|mapfile|readarray|getopts|let)\b")


SPECIAL_VARS = {"PWD", "OLDPWD", "_", "IFS", "RANDOM", "SRANDOM", "SECONDS", "LINENO", "DIRSTACK", "FUNCNAME", "GROUPS", "HISTCMD",
                "KEYBOARD_HACK", "HISTCHARS", "HISTSIZE", "SAVEHIST", "MAILCHECK", "SHLVL", "LISTMAX", "ZSH_SUBSHELL",
                "PS1", "PROMPT", "PS2", "PROMPT2", "RPS1", "RPROMPT",
                "UID", "EUID", "PPID", "EPOCHSECONDS", "EPOCHREALTIME", "PIPESTATUS", "OPTIND", "OPTARG", "OPTERR", "SHELLOPTS", "STATUS",
                "USERNAME", "ERRNO", "ARGV", "ARGC", "GID", "EGID", "TTYIDLE", "COLUMNS", "LINES"}  # compared in upper case (zsh: status, pipestatus)  # the shell rewrites or locks these; BASH* is handled in _stable
SAFE_BETWEEN = re.compile(r"(?:[\w./~:@%+=,\- \t;\n]|&&)*")  # plain words and connectors only: no quotes, escapes, $, redirects


def _stable(command, m, use_at):
    """True when the assignment m is certain to have run, unchanged, when the text at use_at runs."""
    before = re.sub(r"\bexport\s+$", "", NO_OUTPUT.sub("", command[:m.start(1)]))  # the `export ` of this very assignment is not an unsafe word
    between = NO_OUTPUT.sub("", command[m.end():use_at])
    name = m.group(1)
    if name.upper() in SPECIAL_VARS or name.upper().startswith("BASH") or command[use_at - 1:use_at] == "'":
        return False  # rewritten by the shell itself / inside single quotes the $ is literal text
    own = re.sub(r"\$\{%s\}|\$%s\b" % (re.escape(name), re.escape(name)), "x", between)  # other uses of the same variable are plain words
    if not SAFE_BETWEEN.fullmatch(own):
        return False  # anything else between the assignment and the use (quotes, $X, p""rintf, eval) may rebind the name
    text = before + " " + between
    if COMPOUND.search(text) or "<<" in text or "#" in text or re.search(r"(?:^|[;&\n]\s*)\.\s", text):
        return False  # if / loops / heredocs / comments / dot-source: the assignment may not run, or may run again changed
    if re.search(r"""['"\\]""", before) or "\\" in between:  # quotes or escapes before the assignment: it may be text inside a string (\; or mixed quotes)
        return False
    if UNSAFE_AROUND.search(before.replace("&&", " ")) or UNSAFE_AROUND.search(between.replace("&&", " ")):
        return False
    if re.search(r"(?<![\w$])%s\b" % re.escape(m.group(1)), between, re.I):  # the name is rebound: S=..., unset S, read S, for S (any case: cdpath/CDPATH, manpath/MANPATH are tied in zsh)
        return False
    if "&&" in before:  # the assignment may be skipped (false && S=/tmp/a): only a chain of && up to the use is safe
        return not re.search(r"[;\n]", between)
    return True


def expand_assigned(command):
    """Replace $VAR / ${VAR} with the literal assigned earlier in the same command (S=/tmp/x; rm -rf $S/a), so the rm
    check judges the real path. Only when the assignment surely ran, unchanged, before the use; otherwise $VAR stays
    as written and the rm asks."""
    assigns = list(ASSIGN.finditer(command))
    if not assigns or not command.isascii():  # non-ASCII names: shells disagree on where a name ends, so never resolve
        return command
    names = "|".join(sorted({re.escape(m.group(1)) for m in assigns}, key=len, reverse=True))
    out, last = [], 0
    for use in re.finditer(r"\$\{(%s)\}|\$(%s)\b" % (names, names), command):
        name = use.group(1) or use.group(2)
        if use.group(2) and not re.match(r"""(?:$|[\s/;&".'])""", command[use.end():use.end() + 1]):
            continue  # zsh: $S[6,20], $S:h, $S:s/a/b/ change the value after the text was pasted
        prior = [m for m in assigns if m.group(1) == name and m.end() <= use.start()]
        if prior and _stable(command, prior[-1], use.start()):
            out += [command[last:use.start()], next(g for g in prior[-1].groups()[1:] if g is not None)]
            last = use.end()
    return "".join(out) + command[last:]


_STR = r"""(?:'{c}'|"{c}")"""  # one whole string: its content holds no quote, so quotes can never be mispaired
_C = r"""[^'"$`\\\n]*"""
_ARG = _STR.format(c=r"""(?!--o|--ext|--te)""" + _C)  # git accepts abbreviations: --out, --ext-d, --textc
_MOD = r"(?<![\w.])(?:subprocess|__import__\(" + _STR.format(c="subprocess") + r"\))"
READ_ONLY_GIT_CALL = re.compile(
    _MOD + r"\s*\.\s*(?:check_output|run|check_call|call)\(\s*\[\s*" + _STR.format(c="git")
    + r"(?:\s*,\s*" + _STR.format(c="-C") + r"\s*,\s*" + _STR.format(c=_C) + r")?"
    + r"\s*,\s*" + _STR.format(c="(?:show|ls-files|diff|log|status)") + r"(?:\s*,\s*" + _ARG + r")*\s*,?\s*\]"
    + r"(?:\s*,\s*(?:text|check|capture_output|encoding|stderr)\s*=\s*[\w.'\"/-]+)*\s*\)")
PLAIN_IMPORT = re.compile(r"(?m)^[ \t]*import[ \t]+(?![^\n]*\bas\b)[\w., \t]+$")
DYNAMIC_PYTHON = re.compile(r"__import__|importlib|getattr|\beval\b|\bexec\b|compile\(|globals|builtins")


def strip_read_only_git(command):
    """The command without inline-python calls that only run read-only git (list form, literal args, no shell) and without
    plain `import ...` lines, so RUNS_COMMANDS judges what is left. `from subprocess import x`, `as` aliases, shell=True,
    other programs, other git subcommands and dynamic imports stay in the text and still ask."""
    if "<<<" in command or re.search(r"""<<(?!-?[ \t]*(?:['"]|\\[^\n]))""", command):
        return command  # here-string or a heredoc delimiter that is not quoted ('E', "E", \E; a backslash before a newline is a line continuation, so unquoted): the shell still expands $(...) and backticks in the body
    stripped, n = READ_ONLY_GIT_CALL.subn("", command)
    if not n or DYNAMIC_PYTHON.search(stripped):  # a bare `import subprocess` alone still asks
        return command
    return PLAIN_IMPORT.sub("", stripped)


def tea_read_only(seg):
    words = seg.split()
    return words[:1] == ["tea"] and (words[1:2] in (["--version"], ["--help"], ["whoami"]) or words[2:3] in
                                     [[v] for v in TEA_READ_ONLY])


CONNECTOR = re.compile(r"&&|\|\||\|&|(?<![<>&|])&(?![>&])|[;|\n]")  # a lone & too, but not >&, &>, 2>&1


def _part_segments(part):
    orig = shell_words(part)
    kept = [(k, w) for k, w in enumerate(orig) if not re.match(r"^\w+=", w)]  # env assignments are not the command
    words = [w for _, w in kept]
    # /usr/bin/git, /usr/bin/env: a wrapper or git named by path is judged by its name
    named = [os.path.basename(w) if "/" in w and os.path.basename(w) in WRAPPERS | {"git", "gh"} else w for w in words]
    # the real command is the first word, or follows wrappers: sudo git push, xargs git push, bash -c "git push"
    # (a "git push" that is only an argument, like echo "git push", is text and does not count)
    for i in range(len(words)):
        if not starts_command(named, i):
            continue
        seg = Seg(" ".join(named[i:i + 1] + words[i + 1:]))
        seg.words = orig[kept[i][0]:]  # an assignment after the command (`rm x=y`) is an argument
        yield seg
        if re.search(r"\s", words[i]):  # env -S 'rm x', sudo -s 'rm x': the word is a whole command line the wrapper splits
            try:
                inner = shlex.split(words[i]) + orig[kept[i][0] + 1:]
            except ValueError:
                inner = words[i].split() + orig[kept[i][0] + 1:]
            again = Seg(" ".join(inner))
            again.words = inner
            yield again
        if named[i] == "git":  # git --no-pager -C dir -c k=v push → git push
            j = i + 1
            while j < len(words) and words[j].startswith("-"):
                j += 2 if words[j] in GIT_OPTS_WITH_VALUE else 1
            if j > i + 1:
                yield Seg(" ".join(["git"] + words[j:]))


def segments(command):
    # one entry per simple command: split on ; && || | & newlines, drop subshell parens and env assignments
    for part in re.split(CONNECTOR, command):
        yield from _part_segments(part)


def split_commands(command):
    """[(simple command text, connector after it)]: like segments() it splits on ; && || | & newline, but never inside
    quotes, so `rm "a;b"` stays one command."""
    parts, start, i, quote = [], 0, 0, None
    while i < len(command):
        c = command[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            quote = None if c == quote else quote
            i += 1
            continue
        if c == "\\":
            i += 2
        elif c in "'\"":
            quote, i = c, i + 1
        else:
            m = CONNECTOR.match(command, i)
            if m:
                parts.append((command[start:i], "|" if m.group() == "|&" else m.group()))
                i = start = m.end()
            else:
                i += 1
    parts.append((command[start:], ";"))
    return parts


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


# read_only_commands: anything that could write or run what it was not asked to is refused before the list is consulted
READ_REFUSED = re.compile(r"""[>&`(){}]|\$['"]|<<""")
SED_PRINT = re.compile(r"""sed\s+-n\s+(['"]?)\d+(?:,\d+)?p\1(?:\s+[^\s'"$`\\-][^\s'"$`\\]*)+""")  # sed -n 5,9p file: no -i, no w command


def read_only(command, policy):
    """True when every simple command is on policy read_only_commands (or is `sed -n Np file`) and nothing in the text can
    write: redirections, background jobs, substitutions, heredocs, a leading VAR=x, --output / --pre. Fail closed: an empty
    or missing list, or anything unrecognised, is not a read."""
    patterns = policy.get("read_only_commands", [])
    plain = NO_OUTPUT.sub(" ", command)
    pieces = [p for p in (p.strip() for p in re.split(r"&&|\|\||[;|\n]", plain)) if p]
    if not pieces or not patterns:
        return False
    for piece in pieces:
        if READ_REFUSED.search(piece) or READ_OPTS.search(piece) or "$(" in piece:
            return False
        if not (SED_PRINT.fullmatch(piece) or any(fnmatch.fnmatchcase(piece, pat) for pat in patterns)):
            return False
    return True


def protected(command, policy, cwd=None):
    """A protected path (the setup's own rules) that the command looks like it writes to."""
    if read_only(command, policy):  # cat / grep / git diff / sed -n Np: the words rm, cp, tee in their text are not writes
        return None
    plain = NO_OUTPUT.sub("", command)
    inline = INLINE_CODE.search(command) or re.search(r"\b(?:python3?|node|ruby)\s+(?:-\S+\s+)*-[ce]\b", command)
    if inline:  # judge the code by what it calls, and the shell around it by WRITES (its text holds > and the like)
        shell = re.sub(r"""(?s)-[ce]\s+(["']).*?(?<!\\)\1|<<-?\s*['"]?(\w+)['"]?\n.*?\n\2\b""", " ", plain)
        if not (CODE_WRITES.search(command) or WRITES.search(shell)):
            return None
    elif not WRITES.search(plain):
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


def review_write(command, policy):
    """The first path under <dev_root>/reviews/ that the command writes to (a redirection, cp / mv / tee target...): reports
    are written by sub-review only. Inline code is judged by the paths it names. A relative path after a cd is not followed."""
    reviews = os.path.join(os.path.expanduser(layers.dev_root(policy)), "reviews") + "/"
    inside = lambda word: os.path.normpath(os.path.expanduser(normalize(word))).startswith(reviews.rstrip("/") + "/")
    for seg in segments(command):
        for word in write_targets(seg):
            if inside(word):
                return word
    if CODE_WRITES.search(command):
        return next((w for w in tokens(command) if inside(w)), None)
    return None


def exists(directory, ref):
    return review_report.git(directory, "show-ref", "--verify", "-q", ref) is not None


def default_branch(directory):
    """origin/HEAD, else init.defaultBranch, else main / master: whichever exists first; None = no default, the gate is off."""
    ref = review_report.git(directory, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref.partition("/")[2] or ref
    configured = review_report.git(directory, "config", "init.defaultBranch")
    return next((b for b in ([configured] if configured else []) + ["main", "master"] if exists(directory, "refs/heads/" + b)), None)


def check_report(directory, policy, branch, head, no_review, rule="merge-reviewed"):
    """deny / ask for merging `branch` (at commit `head`) by what its review report says."""
    repo = review_report.repo_name(directory)
    if not repo:
        return "ask", "could not check the review report (git too old or not a repo?): confirm the merge", "merge-unchecked"
    shown = normalize(review_report.report_path(layers.dev_root(policy), repo, branch))
    path = os.path.expanduser(shown)
    try:
        with open(path) as f:
            report = review_report.parse(f.read())
    except OSError:
        problem, report = f"no review report for '{branch}' at {shown}: run sub-review (or /code-review) on the branch first", None
    if report:
        fresh = bool(head and report["commit"] and len(report["commit"]) >= 7 and head.startswith(report["commit"]))
        if not fresh and report["tree"] and head:
            fresh = review_report.git(directory, "rev-parse", "--verify", "-q", head + "^{tree}") == report["tree"]
        problem = None if fresh else (f"review report is stale: it reviewed {report['commit'][:7] or 'no commit'}, "
                                      f"'{branch}' is at {(head or '?')[:7]}; run sub-review again ({shown})")
    if problem and no_review:
        return "ask", f"merging WITHOUT a review report (AI_SETUP_NO_REVIEW=1): {problem}", "merge-without-review"
    if problem:
        return "deny", problem, "merge-gate"
    return "ask", f"'{branch}' has a review report, verdict {report['verdict'] or '?'} [report: {shown}]: confirm the merge", rule


def gh_pr_info(arg, directory):
    """headRefName / headRefOid / baseRefName of the PR `gh pr merge` would merge, or None when gh cannot say."""
    cmd = ["gh", "pr", "view"] + ([arg] if arg else []) + ["--json", "headRefName,headRefOid,baseRefName"]
    try:
        run = subprocess.run(cmd, cwd=directory, capture_output=True, text=True, timeout=5)
        info = json.loads(run.stdout) if run.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return info if isinstance(info, dict) and {"headRefName", "headRefOid", "baseRefName"} <= set(info) else None


def positional(args, with_value):
    """Arguments that are not options (or the values of options that take one)."""
    found, k = [], 0
    while k < len(args):
        if args[k] in with_value:
            k += 2
        elif args[k].startswith("-") and args[k] != "-":
            k += 1
        else:
            found.append(args[k])
            k += 1
    return found


def gate_git_merge(directory, args, current, no_review, policy):
    """Items for one `git merge` run in `directory`; none when the gate does not apply."""
    default = default_branch(directory)
    current = current or review_report.git(directory, "symbolic-ref", "-q", "--short", "HEAD")
    if not default or current != default or {"--abort", "--continue", "--quit", "--skip"} & set(args):
        return []
    specs = positional(args, MERGE_VALUE_OPTS) or [review_report.git(directory, "rev-parse", "--abbrev-ref", "@{upstream}")]
    remotes = (review_report.git(directory, "remote") or "").split()
    found = []
    for spec in filter(None, specs):
        if spec == "-":
            spec = review_report.git(directory, "rev-parse", "--abbrev-ref", "@{-1}") or spec
        remote, _, rest = spec.partition("/")
        name = rest if rest and remote in remotes else spec
        if name == default:  # git merge origin/main on main: a sync, not a merge of new work
            continue
        if not (exists(directory, "refs/heads/" + spec) or exists(directory, "refs/remotes/" + spec)):
            found.append(("deny", f"'{spec}' is not a branch: merge a branch by name so its review report can be found", "merge-gate"))
            continue
        head = review_report.git(directory, "rev-parse", "--verify", "-q", spec + "^{commit}")
        found.append(check_report(directory, policy, name, head, no_review))
    return found


def gate_git_pull(directory, args, current, no_review, policy):
    """Items for one `git pull <remote|.> <branch>` run in `directory`: a merge (or rebase) of that branch into the current one."""
    default = default_branch(directory)
    current = current or review_report.git(directory, "symbolic-ref", "-q", "--short", "HEAD")
    if not default or current != default:
        return []
    remote, *refspecs = positional(args, PULL_VALUE_OPTS) or [None]
    found = []
    for refspec in refspecs:  # no refspec (git pull, git pull origin): the upstream, a sync of the default branch
        name = refspec.lstrip("+").partition(":")[0]
        if name == default:  # git pull origin main on main: a sync, not a merge of new work
            continue
        ref = f"refs/heads/{name}" if remote == "." else f"refs/remotes/{remote}/{name}"
        if not exists(directory, ref):  # the remote-tracking ref may be older than what pull fetches: a known gap
            found.append(("deny", f"'{name}' is not a branch known locally: fetch it by name so its review report can be found", "merge-gate"))
            continue
        head = review_report.git(directory, "rev-parse", "--verify", "-q", ref + "^{commit}")
        found.append(check_report(directory, policy, name, head, no_review))
    return found


def cannot_judge(why, no_review):
    """A merge whose repo cannot be worked out is denied (nothing was checked); the marker makes it an ask."""
    if no_review:
        return ("ask", f"merging WITHOUT a review report (AI_SETUP_NO_REVIEW=1): {why}", "merge-without-review")
    return ("deny", why, "merge-gate")


def merge_gate(command, policy, cwd=None):
    """Deny / ask items for the `git merge` and `gh pr merge` in a command that land on the default branch, judged with the
    folder and branch the shell would be in at that point (cd, git -C, an earlier checkout / switch). Other commands: nothing."""
    found = []
    cur, branch = os.path.normpath(cwd or os.getcwd()), None  # cur None: a folder held in a variable, or `cd -`
    where_to = lambda base, word: None if base is None or word == "-" or re.search(r"[$`]", normalize(word)) else \
        os.path.normpath(os.path.join(base, os.path.expanduser(normalize(word))))
    unknown = "cannot tell which repo this merge runs in: use cd <literal path> or git -C <path>"
    stack, closing = [], 0  # ( ... ): a cd or checkout inside a subshell is undone at its closing parenthesis
    for part in re.split(r"&&|\|\||[;|\n]|(?<![<>&])&(?![>&])", command):  # a lone & (background) also ends a command
        for _ in range(closing):
            cur, branch = stack.pop() if stack else (cur, branch)
        net = part.count("(") - part.count(")")
        stack += [(cur, branch)] * max(net, 0)
        closing = max(-net, 0)
        words = words_of(part)
        k = 0
        while k < len(words) and re.match(r"^\w+=", words[k]):
            k += 1
        if words[k:k + 1] in (["cd"], ["pushd"]):
            target = [w for w in words[k + 1:] if w == "-" or not w.startswith("-")][:1]
            cur, branch = where_to(cur, target[0] if target else "~") if target != ["-"] else None, None
            continue
        for i in range(len(words)):
            # the command word follows wrappers, their flags and env assignments (env FOO=1 git ..., sudo FOO=1 git ...)
            if not (i == 0 or words[i - 1] in EXEC_FLAGS or all(
                    w in WRAPPERS or w.startswith("-") or re.fullmatch(r"\d+[smhd]?|\w+=.*", w) or words[n - 1] in WRAPPER_VALUE_OPTS
                    for n, w in enumerate(words[:i]))):
                continue
            base = cur  # env -C <dir> / env --chdir=<dir> move the folder the command runs in
            for n, w in enumerate(words[:i]):
                chdir = w[len("--chdir="):] if w.startswith("--chdir=") else words[n] if n and words[n - 1] in ("-C", "--chdir") else None
                if chdir is not None and "env" in words[:n]:
                    base = where_to(base, chdir)
            env = [w for w in words[:i] if re.match(r"^\w+=", w)]  # the marker and GIT_DIR count anywhere in the prefix
            no_review = "AI_SETUP_NO_REVIEW=1" in env
            tool = os.path.basename(words[i])
            if tool == "gh" and words[i + 1:i + 3] == ["pr", "merge"]:
                found += [cannot_judge(unknown, no_review)] if base is None else gate_gh_merge(base, words[i + 3:], policy, no_review)
            elif tool == "git":
                where, j, redirected = base, i + 1, False
                while j < len(words) and words[j].startswith("-"):
                    if words[j] == "-C" and j + 1 < len(words):
                        where = where_to(where, words[j + 1])
                    redirected = redirected or words[j].split("=")[0] in ("--git-dir", "--work-tree")
                    j += 2 if words[j] in GIT_OPTS_WITH_VALUE else 1
                sub, args = words[j:j + 1], words[j + 1:]
                if sub in (["checkout"], ["switch"]) and "--" not in args and where:
                    named = [args[n + 1] for n, a in enumerate(args[:-1]) if a in ("-b", "-B", "-c", "-C", "--create", "--orphan")] or \
                        [a for a in positional(args, set())[:1] if exists(where, "refs/heads/" + a)]
                    first = positional(args, set())[:1]
                    unresolved = not named and first and (first[0] == "-" or first[0].startswith("@{") or re.search(r"[$`]", first[0]))
                    branch = named[0] if named else "?" if unresolved else branch  # "?": switched to a branch we cannot name
                elif (sub == ["merge"] and not {"--abort", "--continue", "--quit", "--skip"} & set(args)) or sub == ["pull"]:
                    lost = redirected or where is None or bool({"GIT_DIR", "GIT_WORK_TREE"} & {e.split("=")[0] for e in env})
                    # a pull that names only the default branch (or no refspec) is a sync, not a merge of new work. When the folder is
                    # lost the real default is unknown, so main / master by name stands in for it; when only the branch is unknown
                    # ("?") the name is not enough (git pull . master in a repo whose default is main): compare with the real default
                    if sub == ["pull"] and (lost or (branch == "?" and where)):
                        names = ("main", "master") if lost else (default_branch(where),)
                        if all(r.lstrip("+").partition(":")[0] in names for r in positional(args, PULL_VALUE_OPTS)[1:]):
                            continue
                    if redirected or {"GIT_DIR", "GIT_WORK_TREE"} & {e.split("=")[0] for e in env}:
                        found.append(cannot_judge("a merge with --git-dir / --work-tree / GIT_DIR cannot be checked: use git -C <path>", no_review))
                    elif where is None:
                        found.append(cannot_judge(unknown, no_review))
                    elif branch == "?" and sub == ["pull"]:  # the branch may be the default: judge the refspecs as if it were
                        found += [r for r in gate_git_pull(where, args, default_branch(where), no_review, policy) if r]
                    elif branch == "?":
                        found.append(cannot_judge("cannot tell which branch this merge runs on after a checkout / switch of '-', '@{-1}' or a variable: use the branch name", no_review))
                    else:
                        gate = gate_git_merge if sub == ["merge"] else gate_git_pull
                        found += [r for r in gate(where, args, branch, no_review, policy) if r]
    return found


def gate_gh_merge(directory, args, policy, no_review):
    """Items for `gh pr merge [pr]`: gated when the PR's base is the default branch."""
    if any(a in ("-R", "--repo") or a.startswith(("--repo=", "-R")) for a in args):
        return [("ask", "could not check the review report (-R points at another repo): confirm the merge", "gh pr merge*")]
    default = default_branch(directory)
    if not default:
        return []
    info = gh_pr_info((positional(args, GH_MERGE_VALUE_OPTS) or [None])[0], directory)
    if info is None:
        return [("ask", "could not check the review report (gh pr view failed): confirm the merge", "gh pr merge*")]
    if info["baseRefName"] != default:
        return []
    result = check_report(directory, policy, info["headRefName"], info["headRefOid"], no_review, rule="gh pr merge*")
    return [result] if result else []


# --- rm of what this session created -------------------------------------------------------------------------------
# An agent that cleans up its own scratch work should not ask. The OS records when each file was born, so "created by this
# session" is a fact the guard can check without having seen the command that made it (scripts, python, npx...).
REGENERABLE = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".vite", ".turbo", ".parcel-cache", ".eslintcache",
               ".next", ".DS_Store"}  # rebuilt by the tools on the next run: safe to delete even if they are older
MAX_OWNED_ENTRIES = 20000
TRANSCRIPT_ROOT = os.path.expanduser("~/.claude/")  # the only place a transcript path is believed


def sessions_dir():
    return os.environ.get("AI_SETUP_SESSIONS_DIR") or os.path.expanduser("~/.ai-setup/sessions")


def _birth(st):
    return getattr(st, "st_birthtime", None)  # macOS: no birth time elsewhere, so nothing is ever judged as created here


def session_start(event):
    """Epoch seconds when this session began: the birth of its transcript (Claude), else the time of its first guard call,
    kept in a small file per session id (OpenCode). None when unknown: then nothing counts as created by the session."""
    transcript = event.get("transcript") or ""
    if transcript and os.path.realpath(transcript).startswith(os.path.realpath(TRANSCRIPT_ROOT) + "/"):
        try:
            born = _birth(os.stat(transcript))
            if born:
                return born
        except OSError:
            pass
    session = event.get("session")
    if not session:
        return None
    path = os.path.join(sessions_dir(), re.sub(r"[^\w.-]", "_", str(session))[:80])
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        pass
    now = time.time()
    try:
        os.makedirs(sessions_dir(), exist_ok=True)
        with open(path, "x") as f:  # "x": two hooks racing keep the first time
            f.write(repr(now))
        for old in os.listdir(sessions_dir()):  # forget sessions older than 30 days
            full = os.path.join(sessions_dir(), old)
            if time.time() - os.path.getmtime(full) > 30 * 86400:
                os.remove(full)
        return now
    except FileExistsError:
        try:
            with open(path) as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            return None
    except OSError:
        return None


def owned_zones(policy):
    """Folders where the agent may clean up what it created: dev_root (never the whole home) plus `owned_zones` in a layer."""
    zones = list(policy.get("owned_zones", [])) + [layers.dev_root(policy)]
    return [os.path.realpath(os.path.expanduser(z)) for z in zones if z.strip() not in ("", "~")]


def _born_after(path, start):
    """The path, and everything inside it if it is a folder, was born after `start` (and is not too big to check)."""
    try:
        born = _birth(os.lstat(path))
        if born is None or born < start:
            return False
        if stat.S_ISDIR(os.lstat(path).st_mode):
            count = 0
            for dirpath, dirs, files in os.walk(path, followlinks=False):
                for name in dirs + files:
                    if name.lower() == ".git":  # a repo inside: its history is not scratch
                        return False
                    count += 1
                    born = _birth(os.lstat(os.path.join(dirpath, name)))
                    if count > MAX_OWNED_ENTRIES or born is None or born < start:
                        return False
        return True
    except OSError:
        return False


def _tracked(path):
    """True when git tracks the path (or a file under it), or when that cannot be told: only "not a git repository" is a no."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # a GIT_DIR must not decide for the user's repo
    try:
        result = subprocess.run(["git", "-C", os.path.dirname(path), "ls-files", "--", ":(icase,literal)" + os.path.basename(path)],
                                capture_output=True, text=True, timeout=5, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return True
    if result.returncode != 0:
        return "not a git repository" not in result.stderr
    return bool(result.stdout.strip())


def session_owned(target, cwd, policy, start):
    """True when `rm target` only removes something this session created (or a cache the tools rebuild): inside an owned
    zone, no glob / variable / .., not .git, not the folder the command runs in, born after the session began, all of
    its contents too, and not tracked by git."""
    if cwd is None or re.search(r"[*?\[\]{}$`\\]", target) or ".." in target.split("/"):
        return False
    full = os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
    final = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
    if not any(final.startswith(zone + "/") for zone in owned_zones(policy)) or ".git" in final.lower().split("/"):
        return False
    if target.endswith("/") and os.path.islink(final):  # `rm -rf link/` removes what the link points at
        return False
    here = os.path.realpath(cwd)
    if here == final or here.startswith(final + "/") or not os.path.lexists(final):
        return False
    name = os.path.basename(final)
    if name in REGENERABLE or (name.endswith(".pyc") and os.path.isfile(final) and not os.path.islink(final)):
        return not _tracked(final)
    return start is not None and _born_after(final, start) and not _tracked(final)


def scratch_zones(policy):
    """Folders where rm is always free: `scratch_zones` in a layer. A zone counts only when it is an absolute path (after ~)
    under the real dev_root, is a real folder path (no symlink in it), and is neither `/`, home nor dev_root itself."""
    dev = os.path.expanduser(layers.dev_root(policy))
    zones = policy.get("scratch_zones", [])
    if not os.path.isabs(dev) or not isinstance(zones, list):
        return []
    dev = os.path.realpath(dev)
    found = []
    for z in zones:
        if not isinstance(z, str) or not z.strip():
            continue
        path = os.path.expanduser(z.strip())
        if not os.path.isabs(path):
            continue
        path = os.path.normpath(path)
        if path in ("/", os.path.realpath(os.path.expanduser("~")), dev) or os.path.realpath(path) != path or not path.startswith(dev + "/"):
            continue
        found.append(path)
    return found


def _holds_repo(path):
    """A `.git` at any depth inside the folder (or too many entries to look through): its history is not scratch."""
    count = 0
    for _, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            count += 1
            if name.lower() == ".git" or count > MAX_OWNED_ENTRIES:
                return True
    return False


def scratch_owned(target, cwd, policy):
    """True when `rm target` removes something inside a scratch zone: the same literal rules as session_owned (no glob /
    variable / .., not .git, not the folder the command runs in, it exists, a link is judged by itself), but with no
    age or session test. Never the zone itself, never a folder that holds a repo."""
    if re.search(r"[*?\[\]{}$`\\]", target) or ".." in target.split("/") or target.split("/")[-1] == ".":
        return False
    zones = scratch_zones(policy)
    if not zones or (cwd is None and not os.path.isabs(os.path.expanduser(target))):
        return False
    full = os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(target)))
    final = os.path.join(os.path.realpath(os.path.dirname(full)), os.path.basename(full))
    if not any(final.startswith(zone + "/") for zone in zones) or ".git" in final.lower().split("/"):
        return False
    if (target.endswith("/") and os.path.islink(final)) or not os.path.lexists(final):
        return False
    if cwd is not None:
        here = os.path.realpath(cwd)
        if here == final or here.startswith(final + "/"):
            return False
    return os.path.islink(final) or not os.path.isdir(final) or not _holds_repo(final)


def owned_rm(seg, cwd, policy, start):
    """An `rm` / `rmdir` whose every target is in tmp, was created by this session or is inside a scratch zone."""
    words = rm_words(seg)
    if not words or os.path.basename(words[0]) not in ("rm", "rmdir"):
        return False
    if os.path.basename(words[0]) == "rmdir" and any(_parents_option(w) for w in (words[1:words.index("--")] if "--" in words else words[1:])):
        return False  # rmdir -p also removes the parents, which this session may not have created
    targets = rm_targets(words[1:])
    return bool(targets) and all(_inside_tmp(t) or session_owned(t, cwd, policy, start) or scratch_owned(t, cwd, policy) for t in targets)


def _parents_option(word):
    """-p, a bundle with p (-pv), or --parents (GNU takes any prefix: --parent, --par)."""
    if word.startswith("--"):
        return len(word) > 2 and "--parents".startswith(word)
    return word.startswith("-") and "p" in word


CD_WORD = re.compile(r"(?<![\w./-])(?:cd|chdir|pushd|popd)(?![\w./-])")


def _cd_target(words, cur, part):
    """The folder `cd [-L|-P] [--] <one path>` goes to, or None when that is not certain: any other shape (extra words,
    other options, bare `cd`), a variable, `cd -`, a `..` component (the shell resolves it through links), or a folder
    that does not exist."""
    args = words[1:]
    if args[:1] in (["-L"], ["-P"]):
        args = args[1:]
    if args[:1] == ["--"]:
        args = args[1:]
    if cur is None or len(args) != 1 or re.search(r"[(){}`]", part):
        return None
    target = os.path.expanduser(args[0])
    if "$" in target or target.startswith("-") or ".." in target.split("/"):
        return None
    nxt = os.path.normpath(os.path.join(cur, target))
    return nxt if os.path.isdir(nxt) and os.access(nxt, os.X_OK) else None


def segments_in(command, cwd):
    """(simple command, folder it runs in): follows `cd` so a relative path is judged from the right place. A cd that
    cannot be followed (see _cd_target, subshell, pushd, chdir) leaves the folder unknown, and so does a lone `&` (what follows
    may run beside a cd that went to the background). A cd that may not run (after `&&`, `||` or `|`) is only believed
    by the commands chained to it with `&&`; in a pipeline it runs in a subshell and changes nothing, except the last
    element, which zsh runs in this shell (unknown).
    Commands are split with quotes in mind: that is what `rm` is judged on. The plain split that ignores quotes is also
    run and its extra guesses come last, marked `real = False`: they can only add an ask."""
    cur = os.path.normpath(cwd or os.getcwd())
    # The split below does not understand comments, heredocs, braces or keywords: with any of them (or a quote or a
    # backslash) and a `cd` in the text, a cd it reads may not run (or one that runs may be unseen), so no folder is believed.
    unclean = re.search(r"""['"#{}\\]|<<""", command) or COMPOUND.search(command)
    blind = bool(unclean and CD_WORD.search(command))
    prev, maybe = ";", False  # connector before this part; the folder came from a cd that may not have run
    seen = set()
    for part, after in split_commands(command):
        if maybe and prev != "&&":
            cur, maybe = None, False
        words = words_of(part)
        if blind or (CD_WORD.search(part) and words[:1] != ["cd"]):  # `builtin cd`, `FOO=1 cd`, `time cd`...: not followed
            cur = None
        elif words[:1] in (["pushd"], ["popd"], ["chdir"]):  # bash has no chdir: it may not move at all
            cur = None
        elif words[:1] == ["cd"]:
            nxt = _cd_target(words, cur, part)
            if prev == "||":
                cur = None  # it ran only if the command before failed: unknown
            elif after == "|":
                pass  # a pipeline cd runs in a subshell: this shell stays where it was
            elif prev == "|":
                cur = None  # the last element of a pipeline runs in this shell in zsh
            else:
                cur, maybe = nxt, maybe or prev == "&&"
        for seg in _part_segments(part):
            seen.add((str(seg), tuple(seg.words or ())))
            yield seg, cur
        if after == "&":
            cur = None
        prev = after
    flat = re.sub(r"\$\(|[<>]\(|`|\)", ";", command)  # $( ), ` `, <( ), >( ): the commands inside are commands of their own
    for seg in (*segments(command), *(segments(flat) if flat != command else ())):
        if (str(seg), tuple(seg.words or ())) not in seen:  # same text, other words: still a different command
            seg.real = False
            yield seg, None


CONFIG_SCOPE = {"--global", "--local", "--system", "--worktree", "--show-origin", "--show-scope", "-z", "--null"}


def config_read(seg):
    """`git config --get* / --list / -l ...`: the read flag is the first option after config (scope flags aside) and no other
    option follows, so a value cannot turn it into a write (`git config remote.origin.url x --get` writes)."""
    words = shell_words(seg)
    if words[:2] != ["git", "config"]:
        return False
    rest = words[2:]
    while rest[:1] and rest[0] in CONFIG_SCOPE:
        rest = rest[1:]
    return bool(rest) and (rest[0] in ("--list", "-l") or rest[0].startswith("--get")) and all(
        w in CONFIG_SCOPE or not w.startswith("-") for w in rest[1:]) and "#" not in rest


def bash(command, policy, cwd=None, depth=0, start=None):
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
            result = bash(m.group(2) if m.group(1) else m.group(4), policy, cwd, depth + 1, start)
            if result[0] != "allow":
                found.append(result)
    if PIPE_TO_SHELL.search(command):
        found.append(("ask", "a pipe into a shell runs text nobody read: confirm", "pipe-to-shell"))
    if INLINE_CODE.search(command) and RUNS_COMMANDS.search(strip_read_only_git(command)):
        found.append(("ask", "inline code that starts other commands hides what runs: confirm", "inline-code"))
    if re.search(r"\bgit\b.*\s-c\s+alias\.", command):
        found.append(("ask", "an inline git alias hides the real command: confirm", "git-alias"))
    written = review_write(command, policy)
    if written:
        found.append(("ask", f"'{written}' is a review report: only sub-review writes those, confirm", "review-report-write"))
    gated = merge_gate(command, policy, cwd) if re.search(r"\b(?:merge|pull)\b", command) else []  # only merges and pulls: a bug here touches no other command
    found += gated
    for seg, here in segments_in(expand_assigned(command), cwd):
        is_rm, outside = rm_outside_tmp(seg)
        if xargs_rm(seg):
            found.append(("ask", "'xargs rm' deletes what its input names: confirm", "rm-outside-tmp"))
            continue
        if outside and seg.real and owned_rm(seg, here, policy, start):
            continue  # it deletes what this session created: nothing to confirm
        if outside:
            found.append(("ask", f"'rm {outside}' deletes outside tmp: confirm", "rm-outside-tmp"))
            continue
        if is_rm or tea_read_only(seg):  # rm inside tmp, tea list/view: nothing to confirm
            continue
        for pattern in policy["ask_commands"]:
            if pattern.startswith("git config ") and config_read(seg):
                continue  # git config --get / --list read; the url patterns are for writes
            text = seg.lower() if pattern.startswith(("git config ", "git remote ")) else seg  # git section and key names ignore case
            if fnmatch.fnmatchcase(text, pattern) or fnmatch.fnmatchcase(text, pattern.rstrip(" *")):
                # the gate already judged a merge; a push of a branch that push_allow names needs no OK
                if not (gated and pattern in GATE_RULES) and not (pattern == "git push *" and safe_push(seg, command, policy)):
                    found.append(("ask", f"'{seg}' needs your explicit OK (policy: {pattern})", pattern))
                break
    for item in found:
        if item[0] == "deny":  # a deny wins over any ask in the same command
            return item
    if found:
        return max(found, key=lambda r: risk_of(r[0], r[2]) == "high")  # max keeps the first of equals
    return "allow", "", "-"


PUSH_TAINT = re.compile(r"""\bgit\s+-|\.git/|(?<![\w.-])\.git(?![\w.-])|\bxargs\b|(?<![\w-])(?:-c|--config-env|--git-dir|--work-tree|--exec-path|--namespace)(?=[=\s]|$)|\bGIT_\w+=|"""
                        r"""\bgit\b[^;&|\n]*?\s(?:config|remote)\b""")  # a command line that can change where `origin` points
BRANCH = re.compile(r"[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9_-][\w.-]*)*")


def _push_branch(ref, branches):
    name = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    return name if (BRANCH.fullmatch(name) and ".." not in name and not name.endswith((".", ".lock"))
                    and any(fnmatch.fnmatchcase(name, b) for b in branches)) else None


def safe_push(seg, command, policy):
    """True for `git push [-u] <remote> <branch>` where remote and branch are both named by policy push_allow (a layer key)
    and the branch is spelled out (ai/x, ai/x:ai/x, HEAD:ai/x, refs/heads/ai/x). No other flag, no deletion, no tag, no
    + (force), no bare HEAD, no refspec list, and no git option or config command in the line that could move the destination."""
    allow = policy.get("push_allow") or {}
    remotes, branches = allow.get("remotes"), allow.get("branches")
    words = NO_OUTPUT.sub(" ", seg).split()
    # quotes and backslashes are dropped first: git '-C' x, git \-C x and g'i't -C are the same line to the shell
    if not remotes or not branches or words[:2] != ["git", "push"] or PUSH_TAINT.search(re.sub(r"""["'\\]""", "", command)):
        return False
    flags = [w for w in words[2:] if w.startswith("-")]
    args = [w for w in words[2:] if not w.startswith("-")]
    if any(f not in ("-u", "--set-upstream") for f in flags) or len(args) != 2 or args[0] not in remotes:
        return False
    if ":" not in args[1]:  # `ai/x` pushes the branch of that name
        return _push_branch(args[1], branches) is not None
    src, _, dst = args[1].partition(":")
    target = _push_branch(dst, branches)
    return target is not None and (src == "HEAD" or _push_branch(src, branches) == target)


def write_targets(seg):
    """Paths a simple command writes to: redirections, the destination of cp / mv / ln / install / rsync,
    the arguments of mkdir / touch / chmod / chown / truncate / tee, and the file of sed -i."""
    words = re.sub(r"(\d*>>?)", r" \1 ", seg).split()  # echo x>/opt/a → echo x > /opt/a
    found = []
    for i, w in enumerate(words):
        m = re.fullmatch(r"\d*(>>?)(\S*)", w)
        if m:
            target = m.group(2) or (words[i + 1] if i + 1 < len(words) else "")
            if target and not target.startswith("&"):
                found.append(target)
    cmd = os.path.basename(words[0]) if words else ""
    args = [w for w in words[1:] if not w.startswith("-") and not re.match(r"\d*>", w)]
    if cmd in ("cp", "mv", "ln", "install", "rsync") and len(args) >= 2:
        found.append(args[-1])
    elif cmd in ("mkdir", "touch", "chmod", "chown", "truncate", "tee"):
        found += args[1:] if cmd in ("chmod", "chown") else args
    elif cmd == "sed" and any(w.startswith("-i") for w in words[1:]) and args:
        found.append(args[-1])
    return found


def write_outside_safe_zone(command, policy, cwd=None):
    """Outside the sandbox nothing walls the disk: the first written path that is not where the sandbox lets Bash write
    (the current folder, the work folder dev_root, tmp, sandbox.allow_write caches). A relative path is judged from the
    folder the last `cd` left; a path built from a variable other than HOME / TMPDIR cannot be judged: skipped."""
    home = os.path.expanduser("~")
    cwd = os.path.normpath(cwd or os.getcwd())
    safe = [os.path.expanduser(p).rstrip("/") for p in policy.get("sandbox", {}).get("allow_write", [])]
    safe += [p.rstrip("/") for p in TMP_PREFIXES if not p.startswith("$")] + ["/dev"]
    safe += [p for p in (os.path.expanduser(layers.dev_root(policy)), cwd) if p != home]
    cur = cwd
    for part in re.split(r"&&|\|\||[;\n]", NO_OUTPUT.sub("", normalize(command))):
        words = words_of(part)
        if words[:1] == ["cd"]:
            target = os.path.expanduser(words[1]) if len(words) > 1 else home
            cur = target if target.startswith("$") else os.path.normpath(os.path.join(cur, target))
            continue
        for seg in segments(part):
            for word in write_targets(seg):
                if word.startswith("$") or cur.startswith("$") and not word.startswith(("/", "~")):
                    continue  # $TMPDIR/x, $S/x, or relative to a folder held in a variable
                full = os.path.normpath(os.path.join(cur, os.path.expanduser(word)))
                if not any(full == s or full.startswith(s + "/") for s in safe):
                    return word.replace(home, "~")
    return None


def unsandboxed(command, policy, cwd, decision, reason, rule):
    """A call that leaves the OS sandbox: it runs on its own (and is listed in the receipt) unless it also earns an ask,
    writes outside the safe zone, or is one of the policy's unsandboxed_ask_commands (the setup's own installer)."""
    note = "runs outside the sandbox, which removes the OS wall"
    if decision == "ask":
        return "ask", f"{note}. Also: {reason}", rule
    target = write_outside_safe_zone(command, policy, cwd)
    if target:
        return "ask", f"{note} and writes to '{target}', outside the work folder and tmp: confirm", "outside-sandbox-write"
    for seg in segments(command):
        for pattern in policy.get("unsandboxed_ask_commands", []):
            if fnmatch.fnmatchcase(seg, pattern) or fnmatch.fnmatchcase(seg, pattern.rstrip(" *")):
                return "ask", f"'{seg}' {note} (policy: unsandboxed_ask_commands {pattern}): confirm", "outside-sandbox"
    return "allow", "", "outside-sandbox"


def judge(event, policy):
    if event.get("tool") == "bash":
        command, cwd = event.get("command", ""), event.get("cwd")
        decision, reason, rule = bash(command, policy, cwd, start=session_start(event))
        if event.get("unsandboxed") and decision != "deny":
            return unsandboxed(command, policy, cwd, decision, reason, rule)
        return decision, reason, rule
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


SECRET_VALUE = re.compile(r"(?i)\b(authorization:\s*(?:bearer|basic|token)?\s*|bearer\s+|"
                          r"[\w-]*(?:token|secret|passw(?:or)?d|api[_-]?key)[\w-]*\s*[=:]\s*)([^\s'\"]+)|"
                          r"\b(gh[pousr]_\w+|github_pat_\w+|sk-[\w-]{10,}|xox[abp]-[\w-]+|AKIA\w{12,})\b")


def looks_like_path(word):
    """A long string with slashes is kept when no part of it looks like a key: no + or =, every part under 40 chars,
    and none of 12+ chars mixing upper case, lower case and digits (base64 does; folder names rarely do)."""
    parts = [p for p in word.split("/") if p]
    return "/" in word and not re.search(r"[+=]", word) and all(
        len(p) < 40 and not (len(p) >= 12 and re.search(r"[A-Z]", p) and re.search(r"[a-z]", p) and re.search(r"\d", p))
        for p in parts)


def redact(command):
    """The command as it goes into the action log: secret-looking values replaced by ***, one line, at most 240 chars."""
    text = SECRET_VALUE.sub(lambda m: (m.group(1) + "***") if m.group(1) else "***", command)
    text = re.sub(r"\b[A-Za-z0-9+/_.-]{40,}={0,2}", lambda m: m.group(0) if looks_like_path(m.group(0)) else "***", text)
    text = " ; ".join(l.strip() for l in text.splitlines() if l.strip())
    return text if len(text) <= 240 else text[:237] + "..."


def notable(event, policy, decision, rule):
    """(risk, rule) of a command the user should see in the receipt, or None. Asked and denied ones are listed with
    their risk; an allowed one only when it ran outside the sandbox or matches the policy's log_commands."""
    if event.get("tool") != "bash":
        return (risk_of(decision, rule), rule) if decision != "allow" else None
    if decision != "allow":
        return risk_of(decision, rule), rule
    if rule == "outside-sandbox":
        return "medium", rule
    for seg in segments(event.get("command", "")):
        for pattern in policy.get("log_commands", []):
            if fnmatch.fnmatchcase(seg, pattern) or fnmatch.fnmatchcase(seg, pattern.rstrip(" *")):
                return "low", pattern
    return None


def actions_log_path(policy=None):
    """AI_SETUP_ACTIONS_LOG, else <dev_root>/logs/actions.log (dev_root of the layers, home when none sets one)."""
    given = os.environ.get("AI_SETUP_ACTIONS_LOG")
    if given:
        return os.path.expanduser(given)
    try:
        dev = layers.dev_root(load() if policy is None else policy)
    except (OSError, ValueError):
        dev = "~"
    return os.path.expanduser(os.path.join(dev, "logs", "actions.log"))


def log_action(event, decision, risk, rule, reason=""):
    """One line per notable command in AI_SETUP_ACTIONS_LOG (default <dev_root>/logs/actions.log; "off" disables): time,
    session, risk, what happened (ran / asked / denied), rule, redacted command. The task receipt reads it."""
    path = actions_log_path()
    if path == "off":
        return
    what = {"allow": "ran", "ask": "asked"}.get(decision, decision)
    text = redact(event.get("command", "")) if event.get("tool") == "bash" else event.get("name", "?")
    tag = REPORT_TAG.search(reason)
    if tag:  # a merge the gate let through to the user names the report it found
        text += " " + tag.group(0)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".1")
        with open(path, "a") as f:
            f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"), event.get("session") or "?",
                               risk.upper(), what, rule, text]) + "\n")
    except OSError:
        pass


def decide(event, policy=None, log=False):
    """(decision, reason). log=True is for the adapters that answer a real agent; tests and callers stay quiet."""
    policy = policy or load()
    decision, reason, rule = judge(event, policy)
    reason = labelled(decision, reason, rule)
    if log:
        log_decision(event.get("tool", "?"), decision, rule)
        hit = notable(event, policy, decision, rule)
        if hit:
            log_action(event, decision, *hit, reason)
    return decision, reason


def main():
    try:
        decision, reason = decide(json.load(sys.stdin), log=True)
    except Exception as exc:  # a broken guard must not silently allow: ask instead
        decision, reason = "ask", f"policy guard failed ({exc}); confirm manually"
    print(json.dumps({"decision": decision, "reason": reason}))


if __name__ == "__main__":
    main()
