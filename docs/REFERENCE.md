# ai-setup reference

Details moved out of the [README](../README.md). Design notes: [DESIGN.md](DESIGN.md).

## Spend fewer tokens (Claude Code)
| Piece | What it does | When |
|---|---|---|
| **`coach` skill** | Before a task: which model and effort to use, and your request rewritten as goal · done when · out of scope · where to start | `/coach` or "which model should I use?" |
| **Context notice** (hook) | One info line when the session passes 100k tokens, then every 50k. Never blocks; thresholds via `CLAUDE_CONTEXT_NOTICE_START` / `_STEP` | Every prompt |
| **Usage audit** (`adapters/claude/usage_report.py`) | Reads your own transcripts: sessions over 150k, models, top tools, guard decisions, and an ask-fatigue baseline (asks per day, ask rate per ISO week, approval rate from the outcome lines, top 5 ask rules). Local only, sends nothing | On demand |

The notice you see in the chat: `Context is 180k tokens. Long sessions cost more and answer worse: say handoff and I write it, then /clear.`

What `coach` answers (example):
```text
Task: bug
Model: sonnet · effort medium
- reproduce first, strong model only if it stays unclear
Prompt (copy):
> Goal: login returns 500 when the email has a "+"
> Done when: a failing test reproduces it, then passes
> Out of scope: the signup form
> Start from: src/auth/login.ts
Missing: which environment fails? (default: local)
```
`tune-setup` closes the loop: every ~30 days it reads your `/insights` data and proposes a diff to re-tune `coach`, the notice thresholds and `grillme`. It edits only after you approve.

## Limits
- **macOS first.** Linux works for the guard, the installer and the tests (CI runs Ubuntu); `bootstrap.py` lists the brew packages
  for your own package manager instead of installing them. No Windows.
- **A seatbelt, not a wall.** The guard now judges what is inside `bash -c`, `eval`, `curl ... | sh` and inline `python -c`
  that starts commands, and follows `cd` before a relative secret name. Inline code that only reads the setup's rules (`json.load(open('core/policy.json'))`) does not ask; code that writes them (`open(..., 'w')`, `write_text`, `os.remove`, `writeFileSync`) does. Inline Python that only calls `subprocess` for read-only git (`show`, `ls-files`, `diff`, `log`, `status`, list form, literal args) does not ask either. A command line made only of `read_only_commands` (`cat`, `grep`, `git diff`, `sed -n 5,9p`...) never asks about a protected path, even when its text holds `rm` or `cp`. `rm` of something the session created (its birth time is after the session start, it is not tracked by git, and every file inside is that new) inside `dev_root` or a layer's `owned_zones`, or of a regenerable cache (`__pycache__`, `.pytest_cache`...), does not ask. So does `rm` / `rmdir` of anything inside a `scratch_zones` folder (a layer's policy key, list of paths, `~` allowed, default none), with no age or session test: the target must be a literal path (no glob, variable, `..`), exist, and not be the zone itself, a `.git`, a folder with a `.git` at any depth, or a path through a symlink (`zone/lnk` the link itself goes, `zone/lnk/x` and `zone/lnk/` ask). A zone counts only if it is absolute, a real path (no symlink in it), inside `dev_root`, and not `/`, home or `dev_root` itself. It must also sit inside the sandbox's `allow_write` (`dev_root` already is). Limits: a file the user or another session creates after this session started counts as new, and an in-place rewrite (`sed -i`) of an untracked file resets its birth time; a repo with a `.git` inside, and `rm dir/` through a symlink, still ask. Regenerable caches (`.next`, `.vite`, `.DS_Store`...) go by name, so old data inside them goes too. A `cd` the guard cannot read with certainty (quotes, comments, heredocs, braces, `builtin cd`) makes relative paths ask. It follows only `cd [-L|-P] [--] <one path>` with no `..` in the path; anything else (`chdir`, `pushd`, extra words, the last element of a pipeline, anything after a lone `&`) leaves the folder unknown. `rm` is judged on the real shell words (a quoted word is one target), `env -S 'rm x'` counts as `rm x`, and `xargs rm` always asks. The same guard also asks for `git remote set-url` / `remote add` and `git config` of a `remote.*` or `*url*` key (reads with `--get` / `--list` do not), judges commands inside `$( )`, backticks, `<( )` and `>( )` and a `/usr/bin/git` or `/usr/bin/env` named by path like the bare name, and asks when `--output` (any prefix, also spelled with an escape or a variable) or a `sed` `w` command writes a protected path. It misses a config edit in a folder named by a glob or a substitution (`KnownGaps`). Claude Code only: the OpenCode plugin sends no cwd or session, so rm of what the session created asks as before, and a `scratch_zones` target must be written as an absolute path (a relative one is resolved from the guard process's own folder, not the agent's). This needs file birth times (macOS); elsewhere it asks as before. It still cannot read a script file (`sh deploy.sh`),
  a command built from a variable that is not a plain literal, or base64: those stay as `expectedFailure` in `tests/test_guard.py`. The OS sandbox is the wall (Claude only).
- **Comment bodies.** `gh pr comment` / `gh issue comment <N> [--body-file -|-F -] <<'E'` with a quoted delimiter, the terminator `E` and nothing but whitespace after it is judged by its first line only: the body is text, so a line like `gh pr merge 3` in it does not trip the merge gate (the command still asks as a comment). Secret and protected-path checks still read the whole text. Any other shape (unquoted delimiter, `#N`, a carriage return or control character, extra text before or after, another command) is judged as before.
- **OpenCode** uses a beta plugin API; our side is tested with a fake context, not the real OpenCode. **Codex** gets instructions and skills only.
- **Review history.** `review_report.py header` copies an earlier non-empty report to `<branch>.r<N>.md` before the new one is written (the newest stays at `<branch>.md`, which the merge gate reads); running it twice without a new report adds no round. `review_report.py log --stage 3|4` appends one tab-separated line to `$DEV/logs/reviews.log` (time, repo, branch, round, stage, verdict, findings per severity, read from the issues table: `critical/warning/nit` or `blocking/major/minor/nit`). `ai-audit` practice 1 counts reports in nested folders, one per branch, and reports earlier rounds apart.
- **No telemetry.** The guard keeps a local log (`~/.ai-setup/guard.log`: time, decision, rule; never the command). `AI_SETUP_GUARD_LOG=off` disables it.
- **Action log for the receipt.** `$DEV/logs/actions.log` (`AI_SETUP_ACTIONS_LOG`, `off` disables) lists, per session, what ran
  outside the sandbox, what matched `log_commands` (local commits, installs) and every ask, with its risk. The command is kept
  redacted (tokens, `Bearer`, `*_KEY=`, long opaque strings → `***`; paths stay readable) and cut to 240 chars. Reads and sandboxed work are not listed.
  **How an ask ended** (Claude Code): the line format is unchanged (time, session, RISK, what, rule, command); a later line with the same session and command has `approved`, `declined` or `unknown` in the "what" column, so a reader that only knows `ran` / `asked` / `denied` still works. The guard leaves a pending marker per asked `tool_use_id` in `~/.ai-setup/pending/` (`AI_SETUP_PENDING_DIR`, `off` disables); the `ask_outcome.py` hook (PostToolUse, PostToolUseFailure, SessionEnd, SessionStart) writes `approved` when the tool ran (a failed run counts, unless the error starts with Claude Code's own refusal text ("The user doesn't want to proceed with this tool use", "Permission to use ... has been denied", "Permission for this tool use was denied") or the user interrupted; shell output such as `Permission denied` does not count). `declined` is **inferred**, not reported by Claude Code: the marker was still there when the session ended, or (swept at the next SessionStart) it is older than 24 h and its session is not the current one. A `declined` line is stamped when it is inferred (session end, or the next-session sweep), not when the user decided, so its time is not the decision time: S3 / S5 and any reader must use the `asked` line's time for that. A real user decline might surface as PostToolUseFailure and be recorded as `approved` if the error wording differs from the one the hook recognises (unverified). A tool the user approved but that never ran also reads as `declined`; an approval given more than 24 h after a crash is lost. OpenCode never hears the answer: the plugin's ask is followed by `unknown`. Verified against the Claude Code 2.1.317 binary: `tool_use_id` and `session_id` in the PreToolUse / PostToolUse payloads, `PostToolUseFailure` (`error`, `is_interrupt`), `SessionEnd`; not verified: what a user decline fires (the `PermissionDenied` event is for the auto-mode classifier, so it is not used).
- **Run record.** `core/guard/run_json.py update <ticket> ...` keeps `$DEV/handoffs/<ticket>/run.json` (`ticket-flow` calls it at 0a and at each gate; the ticket must be a plain folder name, and with no policy to read the dev root it fails instead of writing under `~`; `--dev-root DIR` overrides): `sessions`, `branch`, `pr`, `reports`, `rounds` (`stage`, `n`, `verdict`, `report`), `start`, `end`. `--session auto` reads the id that the `ask_outcome` hook stored at SessionStart in `~/.ai-setup/sessions/<hash of the real cwd>` (`AI_SETUP_SESSIONS_DIR`, `off` disables); with none stored it adds nothing and prints a note. The newest session started in a folder wins. A journal for reading; nothing resumes from it.

## Why
- **Seatbelt plus wall.** A regex over shell text can be fooled (base64, commands built inside a script). Those gaps are listed
  openly in the tests (`KnownGaps`); the real wall is the OS sandbox Claude gets from the same policy.
- **One writer per ticket.** `flow-ticket` plans on the strong model, a single `sub-builder` writes in its own git worktree, and
  review, tests and checks run read-only in parallel. Nobody grades their own work.
- **Layers, not forks.** Generic rules live in `core/`; your language, tone and company tools go in private layers loaded with `--layers-dir`.

One folder that configures your AI coding agents (Claude Code, OpenCode, Codex) the same way on every machine:
instructions, skills, agents and a permission policy that asks before anything hard to undo.

It is an **engine plus a generic `core/` layer**. Your own rules (language, tone, work tools, per-repo notes) go in
extra **layers**, which can live in a separate private repo and are loaded with `--layers-dir`.

## What changes compared with a stock Claude Code / OpenCode

Stock tools already have permission prompts, subagents and skills. This repo adds the parts you would otherwise build and maintain by hand:

| Area | Stock setup | With ai-setup |
|---|---|---|
| Shell safety | Per-tool permission patterns, configured separately in each tool | One `policy.json`; a guard that also judges what is inside `bash -c`, `eval` and `curl \| sh`; secrets are a hard `deny` |
| Hard limit | Optional sandbox you configure yourself | The OS sandbox is generated from the same policy (Claude Code) |
| Several tools | Each one has its own config format | The same rules and skills installed into Claude Code, OpenCode and Codex |
| Ticket work | You drive each step yourself | `flow-ticket`: strong model plans, one `sub-builder` writes in its own git worktree, review, tests and checks run read-only in parallel |
| Token cost | You find out on the bill | `coach` picks model and effort before you start; a hook warns when the context passes 100k; `usage_report.py` audits your own sessions locally |
| Repeated processes | Ad-hoc prompts | Skills: `ticket-flow`, `validate`, `setup-commit`, `session-handoff`, `repo-guardrails`, `grillme`, `coach`, `pr-review-ticket` |
| New machine | Manual setup | `bootstrap.py` + `install.sh`: backup first, policy checked before writing, tests in CI |

## Install details
Requirements: macOS with Homebrew and python3 (`xcode-select --install`), or Linux with python3 and your own package manager.

```bash
git clone https://github.com/sebabottero/ai-setup.git ~/Dev/ai-setup   # clone into the final path: the links point to it
cd ~/Dev/ai-setup
./bootstrap.py --dry-run     # shows what it would install, changes nothing
./bootstrap.py               # tools from core/bootstrap.json, then ./install.sh
```
- `./install.sh` runs the tests, then links skills and writes instructions, agents and permissions into every tool it finds.
  Anything it replaces is copied first to `~/.ai-setup-backups/<date>/`. Run it as often as you like: with no changes it touches nothing.
- `./bootstrap.py --check` compares this Mac with the manifests. It never stores secrets: it prints the logins you must do by hand.
- Tested with Claude Code 2.1.312 and OpenCode 2.1.2. Codex gets instructions and skills only: the installer's output is tested in CI, but it was never run inside Codex itself.

## Layers
A layer is any top-level folder with `policy.json`, `AGENTS.md`, `skills/`, `agents/` or `notes/`; no list in the code.
Reserved names: `adapters`, `docs`, `tests`, `build`. Layers only **add**: a layer never removes a rule another one gave.
`install.sh` composes the chosen layers into `build/AGENTS.md` and `build/policy.json`.

| Layer | What it is |
|---|---|
| `core/` | Generic: limits, way of working, agents, skills, permission policy. Always installed. |
| `<yours>/` | Optional: language, tone, work tools, notes for one repo (`notes/*.md` are linked to `$DEV/ai-notes/`; `$DEV` is the `dev_root` a layer sets in its `policy.json`, `~` by default). |

### Keep your layers in another repo
```bash
./install.sh --layers-dir ~/Dev/ai-setup-private --with personal,work
```
- `--layers-dir DIR` (repeatable) adds a folder that holds layers. It is remembered in `~/.ai-setup-profile`.
- `core` always comes from this repo: a layer folder cannot shadow it. If two folders have the same layer name, this repo wins.
- `--only core` · `--with <layer>` · `--uninstall <layer>` (with backup). With no flag the last profile is repeated.
  A new layer is never installed unasked. Choosing fewer layers **removes nothing**.
- `./bootstrap.py --layers-dir DIR` does the same on a clean Mac, using each layer's `bootstrap.json`.
- `./add-skill.sh --layer <name>` writes into that layer's real folder, wherever it lives.
- In a layer's `AGENTS.md` and agents, write `{{LAYER}}` for the layer's own folder (`{{AI_SETUP}}` is this repo).
- A layer's `policy.json` can loosen permissions (`allow_*`), so editing it asks for OK, wherever the layer lives.
  `meta-setup` may edit the layer folders.
- Before writing anything, `install.sh` checks the composed policy (nothing both allowed and asked, every allowed command
  really runs without asking) and stops with the offending rule. Your layers are not covered by this repo's tests, so this is their check.

## How it works
- **`core/`** works for any model and tool. **`adapters/<tool>/`** is what makes each tool work at its best (hooks, plugins,
  sandbox, models). An adapter adds to core and never shadows it: a skill or agent with a core name stops the install.
- **Permissions** (`policy.json`): `ask_commands` / `ask_mcp_tools` prompt for writes (commit, push, merge, deleting). `allow_commands`
  let read-only commands run. `deny_files` / `deny_home_dirs` forbid secrets. Ask and deny always win over allow.
- **`core/guard/guard.py`** decides allow / ask / deny for each command, for every tool. The gaps it cannot see (base64, commands
  built inside a script) are listed in `tests/test_guard.py` (`KnownGaps`). Claude also gets an OS-level sandbox from `policy.json`.
  A command that asks to leave the sandbox is off by default (`sandbox.allow_unsandboxed_commands`). When on, an exit runs
  without asking and goes to the action log, unless it earns an ask anyway, writes outside the current folder / `dev_root` /
  tmp / `allow_write` (`🔴 outside-sandbox-write`), or matches `unsandboxed_ask_commands` (the setup's own installer).

## What it installs in each tool
| | Claude Code | OpenCode | Codex |
|---|---|---|---|
| Instructions (`AGENTS.md`) | `~/.claude/CLAUDE.md` → link | `instructions` in `opencode.json` | `~/.codex/AGENTS.md` → link |
| Skills | `~/.claude/skills/*` → links | `skills` in `opencode.json` | `~/.codex/skills/*` → links |
| Agents (6) | `~/.claude/agents/*.md` (generated) | `~/.config/opencode/agents/*.md` (generated) | — |
| Permissions | `permissions` + hook in `settings.json` | `permissions` in `opencode.json` + plugin | — |

It **merges, not replaces**: in `settings.json` and `opencode.json` it only adds its own entries, and removes rules it generated
earlier that no layer produces any more. Rules you added by hand stay.

| Capability | Claude Code | OpenCode v2 | Codex |
|---|---|---|---|
| Ask for OK / forbid (guard) | PreToolUse hook → `core/guard` | `permission.evaluate` plugin → `core/guard` (beta API: after updating, check that `git push` asks) | ❌ |
| OS-level wall | native `sandbox`: secrets, network, writes | ❌ by default (rules + guard); opt-in `install.py --opencode-sandbox` writes srt settings + launcher | ❌ |
| Protect its own rules | `Edit` asks for OK + sandbox `denyWrite` | `edit` asks for OK + guard | ❌ |
| Models | `tier` → opus / sonnet / haiku + `effort`; subagents without a tier (`general-purpose`) run on Sonnet | `tiers.json` → any provider | — |

## Structure
| Path | What it is |
|---|---|
| `core/AGENTS.md` | Generic instructions: limits, way of working, tools |
| `core/agents/` | `flow-ticket`, `sub-review`, `sub-builder`, `sub-tester`, `leaf-verify`, `meta-setup` |
| `core/skills/` | `ticket-flow`, `pr-review-ticket`, `session-handoff`, `repo-guardrails`, `validate`, `setup-commit`, `grillme`, `coach` |
| `core/policy.json` | Permissions, single source |
| `core/guard/` | Shared allow / ask / deny logic and the layer loader |
| `adapters/` | Per-tool hooks, plugins and settings. Claude: guard hook, a context-size notice hook (info only, above 100k tokens), a `ask_outcome` hook (how a guard ask ended, in `actions.log`), a generic `action_trace` hook (logs the commands that a layer's `policy.json` `trace` rule matches, `[{match: [globs], log: "{{DEV}}/logs/x.log", high_risk: {label: [globs]}}]`, globs run over the program and its non-flag words, so list the subcommands that change something, with the same line format, HIGH-RISK mark and dry-run mark; no rules, no-op; never blocks); `tune-setup` and a re-tune reminder and `usage_report.py` (local usage summary, guard log counts and the ask baseline: asks per day and per week from `guard.log`, approval rate from `actions.log` outcomes linked to the `asked` line by session + command and dated by the ask, `unknown` and unresolved asks reported apart; sends nothing) |
| `tests/` | Guard, layers, bootstrap and a full install into a temporary home. Layers used in tests are in `tests/fixtures/layers` |
| `docs/` | `cheatsheet.html` (visual summary, English and Spanish) and `ANALISIS.md` (what is met and what is missing) |
| `build/` | Generated by the installer. Do not edit |

## Agents
| Agent | Role | Writes |
|---|---|---|
| `flow-ticket` | Orchestrates a whole ticket with the `ticket-flow` skill. Main session | only plans in `$DEV/handoffs` |
| `sub-review` | Skeptical review against requirements | ❌ |
| `sub-builder` | The one writer: implements the approved plan and the docs in the worktree | the allowlist only |
| `sub-tester` | Tests: a failing regression test (bug) or feature cases | tests only |
| `leaf-verify` | Runs format, build and tests, and gives a receipt | ❌ |
| `meta-setup` | Maintains this folder: new skills, rules, reinstall | this repo only |

The code is written by **one** `sub-builder` per ticket, in its own worktree, while `flow-ticket` plans and decides on the strong model. The others read, review or validate.
In OpenCode the config enforces the "Writes" limit; in Claude Code the prompt does (Claude cannot limit paths per subagent).
Launch it with `claude --agent flow-ticket` or pick `flow-ticket` in OpenCode. It only stops at two gates: approve the plan, and hand over.

## Installing a skill from GitHub
```bash
./add-skill.sh https://github.com/owner/repo            # repo with one skill
./add-skill.sh https://github.com/owner/repo skills/foo # repo with several: name the folder
./add-skill.sh --update foo                             # update from its origin (overwrites local patches)
./add-skill.sh --list                                   # where each skill comes from
```
It copies the skill into `<layer>/skills/` (default `core`), records the URL and commit in that layer's `sources.json` and installs
it in every tool. It does not run anything it downloads: read the `SKILL.md` and any script before relying on it.
If a skill lands straight in `~/.claude/skills`, `./install.sh` warns you and `./install.sh --adopt` brings it into a layer.

Third-party skills are not bundled, to keep their licenses and updates with their authors. Two that pair well with `ticket-flow` (see [RECOMMENDED-SKILLS.md](RECOMMENDED-SKILLS.md)):
```bash
./add-skill.sh https://github.com/obra/superpowers skills/systematic-debugging
./add-skill.sh https://github.com/mattpocock/skills skills/engineering/tdd
```

## Backup
Your layers are in your own repo: commit and push there. `./backup.sh [--without <folder>] [target]` makes a verified zip of this
folder in `~/Downloads`; layers kept in another folder are not in it.

For the personal files that are in no repo: `./backup.sh --full DEST [--dry-run]` writes `DEST/ai-personal-YYYYMMDD.tar.age`
(needs `age`, asks for a passphrase) plus a plain `RESTORE.md`. Only an allowlist is read (`$DEV/handoffs`, `$DEV/ai-notes`, Claude `memory/` and `history.jsonl`, dotfiles, a generated Brewfile;
a layer adds its own folders with `backup: {include, exclude, by_hand}` in its `policy.json`, paths relative to `$HOME`, `{{DEV}}` allowed). Secrets, `~/.claude.json`,
`gh` login and transcripts are only listed as "copy by hand". `--dry-run` shows both lists and warns about dirty repos or unpushed branches.
`./backup.sh --restore FILE.age [--home DIR] [--force]` never overwrites unless `--force` (keeps a `.bak`).

## Extending it
Put your own rules in a layer (a folder with the files below); `core/` stays untouched and a layer only **adds**. Then run `./install.sh --with <layer>` and open a new session (the guard reads `build/policy.json` at start).

### Add a permission rule
`<layer>/policy.json`; every key is optional:
```json
{ "ask_commands": ["gh api *", "terraform apply*"], "allow_commands": ["terraform plan*"] }
```
| Key | What it does |
|---|---|
| `ask_commands` | Shell commands that need your OK. Globs: `*` matches anything. |
| `allow_commands` | Shell commands that run without asking (keep them read-only). |
| `log_commands` | Shell commands that run without asking but are listed in the receipt's action log (local commits, installs). |
| `unsandboxed_ask_commands` | Shell commands that ask only when the call leaves the sandbox (the setup's installer). |
| `deny_files` / `deny_home_dirs` | Secrets that are never read (file name globs, home folders). |
| `protected_paths` | Files the agent cannot edit without asking (use `{{AI_SETUP}}` for this repo). |
| `read_only_commands` | Commands that only read (`cat`, `grep`, `git diff`, `sed -n 5,9p`...). A line made only of these never asks about `protected_paths`, even if its text holds `rm` or `cp`. Anything with `>`, `&`, `$(`, a backtick, `<<`, a leading `VAR=x`, `--output` or `--pre`, or any unlisted command, keeps the old check. |
| `push_allow` | `{"remotes": [...], "branches": [...]}` (a layer key, off by default): `git push [-u] <remote> <branch>` with both named runs without asking. The branch must be spelled out (`ai/x`, `ai/x:ai/x`, `HEAD:ai/x`); bare `git push`, `HEAD`, `--force`, `+ref`, tags, `--delete`, `--all`, `--mirror`, a refspec list and `git -c` / `git config` / `git remote` / `xargs` / a `.git` path in the same line still ask. For Claude the installer also adds `Bash(git push <remote> <branch>)` and the `-u` / `--set-upstream` forms to `permissions.allow`, only for a literal branch or a `prefix/*` glob of safe characters (and checks the guard allows each one); the rule alone is wider than the guard (it also matches extra arguments such as `--force`): the hook is what asks, so if the hook is broken or absent the rule widens what runs. The hook still asks on a tainted line, and uninstall takes the rules out. OpenCode has no such rule and keeps asking on `git push`. |
| `ask_mcp_tools` | MCP tools (`server.tool`, globs) that ask first. |
| `work_dirs` | Extra folders the agent may work in. |
| `sandbox` | `allowed_domains`, `allow_write`, `unsandboxed_commands`, `allow_unsandboxed_commands` (Claude). With `install.py --opencode-sandbox`, OpenCode's srt settings reuse `allowed_domains`, `allow_write`, `work_dirs`, `deny_home_dirs`, `deny_files` and `protected_paths`, plus `adapters/opencode/sandbox/extra.json` (OpenCode state dirs, provider hosts); the launcher adds `$PWD` as writable. TO VERIFY: the srt schema was written offline. |

`ask` and `deny` always win over `allow`. `install.sh` checks the composed policy and stops with the offending rule. Editing a `policy.json` asks for your OK because it can loosen permissions.
A rule for **everyone** (not just you) goes in `core/policy.json` with a test in `tests/test_guard.py`; see [CONTRIBUTING.md](../CONTRIBUTING.md).

### Add an agent
`<layer>/agents/<name>.md`: a frontmatter, then the prompt.
```markdown
---
name: security-auditor
description: Read-only security review of a diff. Use before a merge.
edit: none
bash: read-only
claude_tools: Read, Grep, Glob, Bash
tier: balanced
effort: medium
color: red
---
You review code for security problems and never edit files. ...
```
| Field | Values |
|---|---|
| `name`, `description` | Required. The description is what decides when the agent is picked. |
| `mode` | `subagent` (default), `primary` or `all`. |
| `tier` | `strong`, `balanced` or `fast`: which model it runs on (see below). |
| `effort` | `low`, `medium`, `high`, `xhigh`. Claude applies it; OpenCode ignores it for now. |
| `edit` | `none` (default), `all`, or a comma list of path globs it may write. |
| `bash` | `read-only`, `checks` (builds and tests, no git changes) or `all`. |
| `claude_tools` | Comma list of Claude tools, or `*`. |
| `color` | `yellow green blue purple red orange cyan gray`. |

In OpenCode the config enforces `edit` and `bash`; in Claude Code the prompt does. A layer agent cannot reuse a `core` name: the install stops.

### Change the models
`tier` is mapped per tool. Claude: `strong` = opus, `balanced` = sonnet, `fast` = haiku (`CLAUDE_MODELS` in `install.py`). OpenCode: fill `adapters/opencode/tiers.json` with `provider/model` per tier (empty = the session's model), or use `overrides` to move one agent to another tier.

## Changing something
1. Edit `core/…` or `adapters/<tool>/…`  2. `./install.sh`  3. Commit.
Options: `./install.sh --tools claude,opencode` · `--dry-run` · `--home <dir>` (install into another folder, to test).
