# ai-setup reference

Details moved out of the [README](../README.md). Design notes: [DESIGN.md](DESIGN.md).

## Spend fewer tokens (Claude Code)
| Piece | What it does | When |
|---|---|---|
| **`coach` skill** | Before a task: which model and effort to use, and your request rewritten as goal · done when · out of scope · where to start | `/coach` or "which model should I use?" |
| **Context notice** (hook) | One info line when the session passes 100k tokens, then every 50k. Never blocks; thresholds via `CLAUDE_CONTEXT_NOTICE_START` / `_STEP` | Every prompt |
| **Usage audit** (`adapters/claude/usage_report.py`) | Reads your own transcripts: sessions over 150k, models, top tools, guard decisions, and an ask-fatigue baseline (asks per day, ask rate per ISO week, approval rate from the outcome lines, top 5 ask rules). `--ticket <slug>` adds tokens, turns and wall time per ticket from its `run.json`. Local only, sends nothing | On demand |

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
- **Protected paths: native ask everywhere it matched, scoped ask inside ticket worktrees.** Every `Edit(<path>)` ask rule is generated exactly as before (one per `protected_paths` entry, all of them, whichever checkout the installer runs from): they are absolute paths of the main checkout, so they never matched a worktree copy of the same file. Inside a ticket worktree (`<dev root>/worktrees/<repo>/<ticket>/`, the setup's own repo only) the `adapters/claude/hooks/scoped_edit.py` hook (PreToolUse + PostToolUse on `Edit|Write|MultiEdit|NotebookEdit`; logic in `core/guard/scope.py`) judges the same `protected_paths` globs read from the worktree root:
  - a path that is **exactly** one of the paths in that worktree's scope file asks once; the PostToolUse of that approved edit writes a grant, and later edits of that path are allowed for 12 h (`GRANT_TTL`); the scope itself lasts 72 h (`SCOPE_TTL`);
  - any other protected path asks every time; so does a path with `..` or one whose symlinks leave the worktree;
  - an edit of the scopes, pending (`~/.ai-setup/pending`) or sessions (`~/.ai-setup/sessions`) folder asks, under any spelling;
  - outside the worktree, non-protected paths and other repos' worktrees: the hook has no opinion and the normal pipeline decides; a hook error answers `ask`;
  - folder names are compared without case (macOS), and the repo is known by the name of its main checkout (git common dir, or the folder under `worktrees/`), not by the install folder's name.
  The scope file is `~/.ai-setup/scopes/<hash of the worktree>.json` (`AI_SETUP_SCOPES_DIR`, `off` disables; `AI_SETUP_WORKTREES` overrides the worktrees folder), exact relative paths only, bound to the worktree's path and to its `.git` file, so a copy under another name, or a worktree recreated under the same name, grants nothing. The owner creates it: `ticket-flow` gives them, at Gate 1 after the plan OK, `! python3 -I core/guard/scope.py add <worktree> <path>...` for the allowlist paths that are protected (`show` and `clear` too; `clear` at the end of stage 4). The sandbox does not let a command write `~/.ai-setup`, and the installer deliberately does **not** list `scope.py` under `sandbox.excludedCommands`: how Claude Code matches that list against compound lines is not verified, and an entry could let the agent write its own scope. The guard asks for every use of `scope.py` except one plain `scope.py show <worktree>` (quoted, escaped, substituted and chained forms all ask: rule `scope-write`); a permission error makes `scope.py` print the `! ` line to run. A new `add` of a path forgets its grant. A SessionStart warning (from the `ask_outcome` hook) and an install-time check report a missing registration; the installer also warns loudly when it runs from a ticket worktree. Known limits (the ones found so far, not a proof there are no others):
  - a hook that does not run at all (uninstalled, interpreter crash, timeout) leaves the normal pipeline in charge, so a protected file in a worktree is then editable like any other file there;
  - the scope only covers worktrees under `<dev root>/worktrees`, not workspace folders kept elsewhere: there `scope.py add` refuses and protected paths get no hook ask (the same as before this change);
  - a Bash write into a worktree copy of a protected file (for example `echo x > <worktree>/install.py`) is not judged by the Edit|Write hook: the Bash guard judges protected paths only as before (the main checkout's paths), so inside a worktree that write is neither asked nor blocked by this feature;
  - `python3 -m scope` or `python3 -c "import scope"` forms return `allow` from the guard, but they run sandboxed and fail with a permission error when they try to write the scope, so they cannot create one;
  - a hardlink to a protected file inside a worktree is judged by its own name, so it is not recognised as protected; Unicode-equivalent spellings of a path are not normalised;
  - a grant follows any PostToolUse of an ask the hook raised, so an ask that auto mode let through with no human also becomes a grant (the live probe covered headless default mode only);
  - criterion 12's example `tests/test_guard.py` is not in the core `protected_paths`, so it never asked; the scoped approval only exists for files that are protected (for example `core/guard/*`, hooks, `install.py`);
  - the `guard.log` baseline changes: edit decisions (`edit`, rule `scoped-edit`) now count in "asks / guard decisions".
  Decision and trade-off: `DESIGN.md` 6. To see how often asks happen, run `python3 adapters/claude/usage_report.py N` (asks per day, approval rate).
- **macOS first.** Linux works for the guard, the installer and the tests (CI runs Ubuntu); `bootstrap.py` lists the brew packages
  for your own package manager instead of installing them. No Windows.
- **A seatbelt, not a wall.** The guard now judges what is inside `bash -c`, `eval`, `curl ... | sh` and inline `python -c`
  that starts commands, and follows `cd` before a relative secret name. Inline code that only reads the setup's rules (`json.load(open('core/policy.json'))`) does not ask; code that writes them (`open(..., 'w')`, `write_text`, `os.remove`, `writeFileSync`) does. Inline Python that only calls `subprocess` for read-only git (`show`, `ls-files`, `diff`, `log`, `status`, list form, literal args) does not ask either. A command line made only of `read_only_commands` (`cat`, `grep`, `git diff`, `sed -n 5,9p`...) never asks about a protected path, even when its text holds `rm` or `cp`. `rm` of something the session created (its birth time is after the session start, it is not tracked by git, and every file inside is that new) inside `dev_root` or a layer's `owned_zones`, or of a regenerable cache (`__pycache__`, `.pytest_cache`...), does not ask. So does `rm` / `rmdir` of anything inside a `scratch_zones` folder (a layer's policy key, list of paths, `~` allowed, default none), with no age or session test: the target must be a literal path (no glob, variable, `..`), exist, and not be the zone itself, a `.git`, a folder with a `.git` at any depth, or a path through a symlink (`zone/lnk` the link itself goes, `zone/lnk/x` and `zone/lnk/` ask). A zone counts only if it is absolute, a real path (no symlink in it), inside `dev_root`, and not `/`, home or `dev_root` itself. It must also sit inside the sandbox's `allow_write` (`dev_root` already is). Limits: a file the user or another session creates after this session started counts as new, and an in-place rewrite (`sed -i`) of an untracked file resets its birth time; a repo with a `.git` inside, and `rm dir/` through a symlink, still ask. Regenerable caches (`.next`, `.vite`, `.DS_Store`...) go by name, so old data inside them goes too. A `cd` the guard cannot read with certainty (quotes, comments, heredocs, braces, `builtin cd`) makes relative paths ask. It follows only `cd [-L|-P] [--] <one path>` with no `..` in the path; anything else (`chdir`, `pushd`, extra words, the last element of a pipeline, anything after a lone `&`) leaves the folder unknown. `rm` is judged on the real shell words (a quoted word is one target), `env -S 'rm x'` counts as `rm x`, and `xargs rm` always asks. The same guard also asks for `git remote set-url` / `remote add` and `git config` of a `remote.*` or `*url*` key (reads with `--get` / `--list` do not), judges commands inside `$( )`, backticks, `<( )` and `>( )` and a `/usr/bin/git` or `/usr/bin/env` named by path like the bare name, and asks when `--output` (any prefix, also spelled with an escape or a variable) or a `sed` `w` command writes a protected path. It misses a config edit in a folder named by a glob or a substitution (`KnownGaps`). Claude Code only: the OpenCode plugin sends no cwd or session, so rm of what the session created asks as before, and a `scratch_zones` target must be written as an absolute path (a relative one is resolved from the guard process's own folder, not the agent's). This needs file birth times (macOS); elsewhere it asks as before. It still cannot read a script file (`sh deploy.sh`),
  a command built from a variable that is not a plain literal, or base64: those stay as `expectedFailure` in `tests/test_guard.py`. The OS sandbox is the wall (Claude only).
- **Comment bodies.** `gh pr comment` / `gh issue comment <N> [--body-file -|-F -] <<'E'` with a quoted delimiter, the terminator `E` and nothing but whitespace after it is judged by its first line only: the body is text, so a line like `gh pr merge 3` in it does not trip the merge gate (the command still asks as a comment). Secret and protected-path checks still read the whole text. Any other shape (unquoted delimiter, `#N`, a carriage return or control character, extra text before or after, another command) is judged as before.
- **OpenCode** uses a beta plugin API; our side is tested with a fake context, not the real OpenCode. **Codex** gets instructions and skills only.
- **Review history.** `review_report.py header` copies an earlier non-empty report to `<branch>.r<N>.md` before the new one is written (the newest stays at `<branch>.md`, which the merge gate reads); running it twice without a new report adds no round. `review_report.py log --stage 3|4` appends one tab-separated line to `$DEV/logs/reviews.log` (time, repo, branch, round, stage, verdict, findings per severity, then triage counts `fix_now/defer/reject`; read from the severity and triage columns of the issues table, which `sub-review` writes as a fixed table: severity `blocking | major | minor | nit` · triage `fix_now | defer | reject` · one-line reason · file:line · problem · fix; old reports with `critical/warning/nit` are still read, and a table header row is never counted). `review_report.py rounds --stage 3|4` prints `stage=N rounds=R open=O stop=yes|no` from `reviews.log`: with `stop=yes` (2 rounds in the stage and `blocking`/`major` still open) `ticket-flow` does not start round 3 and asks at the next gate. `ai-audit` practice 1 counts reports in nested folders, one per branch, and reports earlier rounds apart.
- **Cross-provider review (criterion 9).** For a ticket whose tier is high (repo `AGENTS.md` "Risk tiers"), Gate 1 offers one opt-in line; the default is off and the choice is stored in `run.json` as `cross_review` (`run_json.py update <ticket> --cross-review on|off`). When on, `ticket-flow` runs a second, read-only reviewer from another provider on the same diff in stages 3 and 4: `cat core/agents/sub-review-xprov.md <brief file> | codex exec --sandbox read-only -` or `opencode run --agent sub-review-xprov --model <non-claude provider/model> --file <brief file> "Review as the attached brief says."`, the brief being a file under `handoffs/<ticket>/` and the prompt never as a quoted argument (the agent text has backticked spans the shell would run); each asks for OK like any command not on the allowlists. These launch commands are not verified end to end: the flags come from the CLIs' help and general knowledge and were not run in a real ticket. With OpenCode `--model` is mandatory and must be a non-Claude model (otherwise it is not a second provider). The orchestrator saves its message at `<branch>.<provider>.md` using `review_report.py header --reviewer <provider>` (header says `Reviewer: <provider>`; an earlier report of that provider is first kept as `<branch>.<provider>.r<N>.md`; `<branch>.md`, the merge gate's report, is untouched; a branch named `<x>.<name>` shares that path with reviewer `<name>` on branch `<x>`, so avoid dotted branch names that end in a provider name). In OpenCode, saving the second report asks for OK each time: `flow-ticket` only edits under `handoffs/*`, and the agent is not widened. `ai-audit` reports such files apart (`+N cross-provider`), not as branch reports. `core/agents/sub-review-xprov.md` is a new agent file. It is installed like every core agent, so it also appears as a Claude subagent; its description says not to use it there.
- **No telemetry.** The guard keeps a local log (`~/.ai-setup/guard.log`: time, decision, rule; never the command). `AI_SETUP_GUARD_LOG=off` disables it.
- **Action log for the receipt.** `$DEV/logs/actions.log` (`AI_SETUP_ACTIONS_LOG`, `off` disables) lists, per session, what ran
  outside the sandbox, what matched `log_commands` (local commits, installs) and every ask, with its risk. The command is kept
  redacted (tokens, `Bearer`, `*_KEY=`, long opaque strings → `***`; paths stay readable) and cut to 240 chars. Reads and sandboxed work are not listed.
  **How an ask ended** (Claude Code): the line format is unchanged (time, session, RISK, what, rule, command); a later line with the same session and command has `approved`, `declined` or `unknown` in the "what" column, so a reader that only knows `ran` / `asked` / `denied` still works. The guard leaves a pending marker per asked `tool_use_id` in `~/.ai-setup/pending/` (`AI_SETUP_PENDING_DIR`, `off` disables); the `ask_outcome.py` hook (PostToolUse, PostToolUseFailure, SessionEnd, SessionStart) writes `approved` when the tool ran (a failed run counts, unless the error starts with Claude Code's own refusal text ("The user doesn't want to proceed with this tool use", "Permission to use ... has been denied", "Permission for this tool use was denied") or the user interrupted; shell output such as `Permission denied` does not count). `declined` is **inferred**, not reported by Claude Code: the marker was still there when the session ended, or (swept at the next SessionStart) it is older than 24 h and its session is not the current one. A `declined` line is stamped when it is inferred (session end, or the next-session sweep), not when the user decided, so its time is not the decision time: S3 / S5 and any reader must use the `asked` line's time for that. A real user decline might surface as PostToolUseFailure and be recorded as `approved` if the error wording differs from the one the hook recognises (unverified). A tool the user approved but that never ran also reads as `declined`; an approval given more than 24 h after a crash is lost. OpenCode never hears the answer: the plugin's ask is followed by `unknown`. Verified against the Claude Code 2.1.317 binary: `tool_use_id` and `session_id` in the PreToolUse / PostToolUse payloads, `PostToolUseFailure` (`error`, `is_interrupt`), `SessionEnd`; not verified: what a user decline fires (the `PermissionDenied` event is for the auto-mode classifier, so it is not used).
- **Run record.** `core/guard/run_json.py update <ticket> ...` keeps `$DEV/handoffs/<ticket>/run.json` (`ticket-flow` calls it at 0a and at each gate; the ticket must be a plain folder name, and with no policy to read the dev root it fails instead of writing under `~`; `--dev-root DIR` overrides): `sessions`, `branch`, `pr`, `reports`, `rounds` (`stage`, `n`, `verdict`, `report`), `start`, `end`. `--session auto` reads the id that the `ask_outcome` hook stored at SessionStart in `~/.ai-setup/sessions/<hash of the real cwd>` (`AI_SETUP_SESSIONS_DIR`, `off` disables); with none stored it adds nothing and prints a note. The newest session started in a folder wins. A journal for reading; nothing resumes from it. `usage_report.py --ticket <slug> [--dev-root DIR]` reads it and prints tokens, turns and wall time of its sessions from `~/.claude/projects/*/<session_id>.jsonl` (`AI_SETUP_PROJECTS_DIR` overrides); a session id without a transcript, or a run.json with no ids, is named as missing and never estimated. `core/scripts/metrics.py --week [2026-W47] [--dev-root DIR]` writes `$DEV/logs/metrics-<YYYY-Www>.md` (this ISO week by default): rounds to PASS per branch (`reviews.log`), ask answers (`actions.log` outcomes, each ask dated by its `asked` line), runs per ticket and tokens and time per ticket (`run.json`), findings by severity and triage (old 7-field and new 8-field review lines), plus the branch's own commits (`origin/main..branch`, else `main..branch`; `n/a` without a base ref) from `git log` of `$DEV/repos/<repo>`. A run.json that is not an object or has no readable `start` is skipped and counted in the file. It reads `AI_SETUP_ACTIONS_LOG`, `AI_SETUP_GUARD_LOG`, `AI_SETUP_REVIEWS_LOG` like the guard, rewrites no log, and ends with an `Outside-sandbox commands` section: the `actions.log` lines that are MEDIUM, `ran`, rule `outside-sandbox` in the week, grouped by command head (env assignments, `cd`/`export` setup segments and path prefixes skipped; the first real command of a compound line), top 15 by count plus `other` and a total, `none` when empty; the text is the already redacted log text. Known limits: each assistant message id is counted once per transcript (Claude Code repeats it on every content-block line); wall time is the sum of per-session spans, not elapsed time; `--ticket` and the per-ticket cost ignore `<session>/subagents/agent-*.jsonl` transcripts (they exist and carry usage), so cost per ticket is understated; `metrics.py` imports `adapters/claude/usage_report.py`, so the token measure is Claude-only; outside-sandbox heads can be a shell keyword or wrapper (`for`, `eval`, `timeout`, `env`, `sudo`) or a path fragment, so a label can be weak while the totals stay exact. Log fields are validated before git runs (plain repo folder under `$DEV/repos`, branch not starting with `-`), and a symlinked output file is refused.

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

### Preferences and HTML views
Two preferences, set by a layer in its `policy.json` (first layer wins; defaults when none sets them): `gate_view` (`md` or `html`, default `md`) and `lang` (language of guides, default `en`). `build/policy.json` always carries both, and the installer prints `preferences: gate_view=<v> lang=<v>`.
`python3 -I core/guard/render_gate.py --prefs` prints them. `python3 -I core/guard/render_gate.py <dir>/criteria.md` (or `plan.md`) writes the sibling `.html` from the `visual-guides` templates: criterion lines verbatim, `<meta name="source-sha256">` with the hash of the `.md`, and a dependency SVG when the `.md` has `## Slices`. The page is self-contained (no external URL). The `.md` stays the source of truth: agents and reviewers keep reading it, never the `.html`. `render_gate.py --check <file>` (the `.md` or its `.html`) exits 0 when the page is fresh and 1 when it is stale or missing. With `gate_view: "html"`, grillme's closing and ticket-flow's 0a and Gate 1 run `--check`, re-render when it fails, and show at most 3 lines plus `! open <absolute path to the .html>`; with `md` no `.html` is written and the gates are unchanged. A `gate_view` that is not `md` or `html` is lowercased, and an unknown value is read as `md` (`--prefs` says so on stderr).

### Human docs in HTML
A repo opts in with one line in its `AGENTS.md` or `CONTRIBUTING.md`: `Human docs: html` (any case, may be a list item). When the ticket-flow docs stage finds it (the grep is in the `visual-guides` skill), the human docs the ticket adds or changes are written as one self-contained `.html` from the `repo-doc` template, always in English. Only the language and the format change; every other rule of the repo's docs still applies. Without the line, the docs stage is unchanged.

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
| `core/agents/` | `flow-ticket`, `sub-review`, `sub-review-xprov`, `sub-builder`, `sub-tester`, `leaf-verify`, `meta-setup` |
| `core/skills/` | `ticket-flow`, `pr-review-ticket`, `session-handoff`, `repo-guardrails`, `validate`, `setup-commit`, `grillme`, `coach`, `visual-guides` |
| `core/policy.json` | Permissions, single source |
| `core/guard/` | Shared allow / ask / deny logic and the layer loader |
| `adapters/` | Per-tool hooks, plugins and settings. Claude: guard hook, a context-size notice hook (info only, above 100k tokens), a `ask_outcome` hook (how a guard ask ended, in `actions.log`), a `scoped_edit` hook (ask once for a ticket's scoped protected paths inside its worktree, `core/guard/scope.py`), a generic `action_trace` hook (logs the commands that a layer's `policy.json` `trace` rule matches, `[{match: [globs], log: "{{DEV}}/logs/x.log", high_risk: {label: [globs]}}]`, globs run over the program and its non-flag words, so list the subcommands that change something, with the same line format, HIGH-RISK mark and dry-run mark; no rules, no-op; never blocks); `tune-setup` and a re-tune reminder and `usage_report.py` (local usage summary, guard log counts and the ask baseline: asks per day and per week from `guard.log`, approval rate from `actions.log` outcomes linked to the `asked` line by session + command and dated by the ask, `unknown` and unresolved asks reported apart; the `Guard:` line now follows the `days` window ("Guard (last N days)" / "Guard (all time)") and no longer says the answer is not recorded; the report notes when `actions.log` rotated to `.1` (not read); sends nothing) |
| `tests/` | Guard, layers, bootstrap and a full install into a temporary home. Layers used in tests are in `tests/fixtures/layers` |
| `docs/` | `cheatsheet.html` (visual summary, English and Spanish) and `ANALISIS.md` (what is met and what is missing) |
| `build/` | Generated by the installer. Do not edit |

## Agents
| Agent | Role | Writes |
|---|---|---|
| `flow-ticket` | Orchestrates a whole ticket with the `ticket-flow` skill. Main session | only plans in `$DEV/handoffs` |
| `sub-review` | Skeptical review against requirements | ❌ |
| `sub-review-xprov` | Second reviewer for Codex or OpenCode with a non-Claude model (cross-provider, opt-in); returns its report as its message. Not for Claude Code | ❌ (edit none) |
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

## How the guard decides
```
 agent runs a command
        │
        ▼
   guard.py (reads policy.json, composed into build/policy.json)
        ├─► allow ─► runs, no prompt          git status, ls, grep
        ├─► ask   ─► you approve, then runs   git push, git reset --hard, git clean
        └─► deny  ─► blocked                  .env.local, SSH and cloud credentials
        │
        ▼
   OS sandbox (Claude; OpenCode opt-in via srt): the wall if the guard misses something
```
The rules are plain JSON in [`core/policy.json`](../core/policy.json) (shortened here):
```json
{
  "ask_commands":   ["git push *", "git reset --hard*", "git clean *"],
  "allow_commands": ["git status", "git diff *", "ls *"],
  "deny_files":     [".env.local", "*.env.local"],
  "deny_home_dirs": ["~/.ssh", "~/.aws"]
}
```
A layer can add rules, never weaken `core/`.


## OpenCode OS sandbox (opt-in)
OpenCode has no OS wall of its own, so by default it gets rules plus the guard only. To add one, install [`srt`](https://github.com/anthropic-experimental/sandbox-runtime) yourself (`npm install -g @anthropic-ai/sandbox-runtime`; ai-setup never installs it) and run:
```bash
./install.sh --opencode-sandbox   # writes ~/.ai-setup/opencode-sandbox.json and ~/.ai-setup/bin/opencode-sandboxed
~/.ai-setup/bin/opencode-sandboxed   # opencode inside srt, built from the same policy.json (srt settings unverified)
```
The settings reuse `policy.json` (allowed domains, `allow_write`, `work_dirs`, secrets, protected paths) and add what OpenCode needs because srt wraps the whole process: its state dirs (writable) and model-provider hosts, listed in `adapters/opencode/sandbox/extra.json` (edit it for the providers you use, then re-run the installer). The launcher adds the folder you start it from to the writable paths at launch. It is not identical to Claude's sandbox. Without the flag nothing is written and the install is unchanged. The srt settings format was written offline and is marked `TO VERIFY` in the launcher: check it against `srt --help` before trusting it.


## The eight layers
Eight layers of a harness, with an honest status. `done` means the evidence path exists on `main`; `partial` says what is missing.

| Layer | Status | Evidence | What is missing |
|---|---|---|---|
| Instructions | done | [`core/AGENTS.md`](../core/AGENTS.md) | One set of rules and skills, installed into Claude Code, OpenCode and Codex (Codex: instructions and skills only). |
| Permissions / guard | done | [`core/guard/guard.py`](../core/guard/guard.py) | `allow` / `ask` / `deny` from one `policy.json`; OS sandbox on Claude. OpenCode sandbox is opt-in and its srt settings are unverified. Protected paths: native ask everywhere, ask-once scoped grants inside ticket worktrees ([DESIGN](DESIGN.md), entry 6). |
| Workflow / agents | done | [`core/skills/ticket-flow/SKILL.md`](../core/skills/ticket-flow/SKILL.md) | Ticket to merge, one writer per ticket, two human gates. |
| Review | done | [`core/agents/sub-review.md`](../core/agents/sub-review.md) | Independent reviewer, findings table, round cap, history in `reviews.log`; optional second reviewer from another provider. |
| Verification | partial | [`core/agents/sub-review.md`](../core/agents/sub-review.md) | One test per criterion and CI; the reviewer lists every criterion without a test as "not covered". Partial: an agent does it, not an automatic check. |
| Observability | partial | [`core/scripts/metrics.py`](../core/scripts/metrics.py) | Sessions, guard ask rates, outcome of asks, tokens/turns/time per ticket (`usage_report.py --ticket`) and a weekly view (`metrics.py --week`) that also lists, by command head, the commands that ran outside the sandbox without asking. Partial: cost per ticket ignores subagent transcripts, so it is understated, and there is no real approval-rate data yet. |
| Knowledge | done | [`core/skills/session-handoff/SKILL.md`](../core/skills/session-handoff/SKILL.md) | Handoffs, per-repo `AGENTS.md` via `repo-guardrails`, a repeated mistake becomes a rule (`meta-setup`, manual). |
| Recovery | partial | [`backup.sh`](../backup.sh) | Backup of the setup and personal files, install backs up what it replaces. No rollback of an agent's edits to your repos. |

Also: `coach` picks model and effort before you start and a hook warns when the context passes 100k. See [The cycle](#the-cycle).

## The cycle
The guard is one piece. Around it, the whole loop of working with an AI agent, from ticket to merge:
```
 1 Decide ─► 2 Guardrails ─► 3 Build ─► 4 Independent ─► 5 Human ─► 6 Learn
                                          review          gate        │
   ▲                                                                  │
   └──────────────── a repeated mistake becomes a rule ◄──────────────┘
```
| # | Step | Covered by |
|---|---|---|
| 1 | **Decide** | `grillme` interviews you and writes `criteria.md`: goal, out of scope, done criteria, and `## Slices` when it should be several small PRs; `ticket-flow` Gate 1 shows a single-PR or split verdict |
| 2 | **Guardrails** | `repo-guardrails`: `AGENTS.md` templates (rules marked `E:` or with an expiry date), risk tiers, CI |
| 3 | **Build** | `ticket-flow` orchestrates, `sub-builder` writes, `sub-tester` writes one test per criterion |
| 4 | **Independent review** | `sub-review` checks the diff against `criteria.md`; the merge gate requires its report; `ticket-flow` re-reviews the committed PR against `criteria.md` and posts it as a PR comment only with your OK |
| 5 | **Human gate** | `ticket-flow` Gate 2 plus the guard's `ask` on commit, push and merge: you decide |
| 6 | **Learn** | `meta-setup` turns a repeated mistake into a rule; `ai-audit` is the periodic check |

Details per step in the [cheatsheet](https://sebabottero.github.io/ai-setup/cheatsheet.html#cycle).

## Measure it
A dated snapshot (2026-11-23) of real numbers from the author's machine. Each figure has the command that produced it; run it on your own logs.

**Rounds to PASS** (stage 3, diff review: rounds until `sub-review` first says PASS), from `~/Dev/logs/reviews.log`:
```console
$ awk -F'\t' '$5==3 && $6=="PASS" && !s[$3]++ {print $3, $4}' ~/Dev/logs/reviews.log
ai/harness-s1-review-history 2
ai/harness-s3-ask-baseline 2
ai/harness-s4-review-quality 1
ai/harness-s5-cost-weekly 2
ai/harness-s6-cross-reviewer 2
```
Clean: s3 2, s4 1, s5 2, s6 2 (4 branches, average 1.75). s1 is only a lower bound (logging started mid-review, its round 1 is missing). s2 and s7 have stage-4 rows only, so they are not comparable.

**Ask approval rate**: no real data yet. The outcome hook (approved / declined per ask) only just merged. Today `AI_SETUP_ACTIONS_LOG=~/Dev/logs/actions.log python3 -I adapters/claude/usage_report.py 30` prints:
```console
Approval rate: n/a (no decided asks); unknown 0, unresolved 1565 (rest of the line abbreviated)
```

**Asks and tokens** (`python3 -I adapters/claude/usage_report.py 30`, 2026-11-23; reads only your local files, sends nothing):
```console
Sessions: 338  |  over 150k: 44 (13%)  |  over 300k: 0  |  peak: 287k
Guard (last 30 days): 10101 allowed, 1528 asked, 46 denied. Rules that fire most: protected_paths 393, git push * 333, rm-outside-tmp 308
Ask rate per week (asks / guard decisions): 2026-W45 9% (208/2273), 2026-W46 11% (493/4423), 2026-W47 17% (660/3922), 2026-W48 16% (167/1057)
  guard.log only covers from 2026-11-03 on: earlier days and the first week are partial
```
Per ticket: `python3 -I adapters/claude/usage_report.py --ticket <slug>`; weekly file: `python3 core/scripts/metrics.py --week`.

`/coach` before a task (example): model and effort, plus your request rewritten as *goal · done when · out of scope · start from*.
Every ~30 days `tune-setup` (Claude only) re-tunes it from your own `/insights` data, and edits only after you approve.

`ai-audit` scores any repo, read-only, on how well it follows the cycle: `python3 -I core/skills/ai-audit/audit.py <repo>`.
Scores are 1-5 and heuristic; "Small changes" measures size per merged PR (per commit when there are no merge commits). In one pilot repo the same cycle took four practices from weak to strong:
```console
Practice                  before → after
3 Enforced rules             1   →  4
4 Real static checks         1   →  5
5 Shared knowledge           2   →  5
7 CI covers what matters     2   →  5
```
Review, criteria-linked tests and the human gate stay at 1 there: `ai-audit` measures them over history, not one change.
