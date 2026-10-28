# ai-setup

[![CI](https://github.com/sebabottero/ai-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/sebabottero/ai-setup/actions/workflows/ci.yml)
[![CI macOS](https://github.com/sebabottero/ai-setup/actions/workflows/ci-macos.yml/badge.svg)](https://github.com/sebabottero/ai-setup/actions/workflows/ci-macos.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**AI coding agents can run `git push`, `rm -rf` or read your SSH keys. This makes them ask first, with the same rules in Claude Code and OpenCode.**

One policy file, one guard, every tool. Design notes: [docs/DESIGN.md](docs/DESIGN.md). The guard decides `allow` / `ask` / `deny` for each shell command (real output):

```console
$ echo '{"tool":"bash","command":"git push origin main"}' | python3 core/guard/guard.py
{"decision": "ask", "reason": "\ud83d\udd34 high risk: 'git push origin main' needs your explicit OK (policy: git push *)"}
$ echo '{"tool":"bash","command":"rm -rf src"}' | python3 core/guard/guard.py
{"decision": "ask", "reason": "\ud83d\udd34 high risk: 'rm src' deletes outside tmp: confirm"}
$ echo '{"tool":"bash","command":"git status"}' | python3 core/guard/guard.py
{"decision": "allow", "reason": ""}
```
Every ask starts with a risk label (`🔴 high risk` or `🟡 medium risk`; a compound command shows its highest). Reading secrets (SSH and cloud credentials, `.env.local`) is a hard `deny`. All of it is covered by `tests/test_guard.py` and the rest of the suite, which runs in CI.

### Limits (read first)
- **macOS first.** Linux works for the guard, the installer and the tests (CI runs Ubuntu); `bootstrap.py` lists the brew packages
  for your own package manager instead of installing them. No Windows.
- **A seatbelt, not a wall.** The guard now judges what is inside `bash -c`, `eval`, `curl ... | sh` and inline `python -c`
  that starts commands, and follows `cd` before a relative secret name. It still cannot read a script file (`sh deploy.sh`),
  a variable-built command or base64: those stay as `expectedFailure` in `tests/test_guard.py`. The OS sandbox is the wall (Claude only).
- **OpenCode** uses a beta plugin API; our side is tested with a fake context, not the real OpenCode. **Codex** gets instructions and skills only.
- **No telemetry.** The guard keeps a local log (`~/.ai-setup/guard.log`: time, decision, rule; never the command). `AI_SETUP_GUARD_LOG=off` disables it.

### Why
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
| Repeated processes | Ad-hoc prompts | Skills: `ticket-flow`, `validate`, `setup-commit`, `session-handoff`, `grillme`, `pr-review-ticket` |
| New machine | Manual setup | `bootstrap.py` + `install.sh`: backup first, policy checked before writing, tests in CI |

## Is it for you?

**Yes, if you:**
- use an AI agent on real repos and want `git push`, deletes and secret reads to need your OK;
- switch between Claude Code, OpenCode and Codex and want the same rules in all of them;
- work from tickets and want planning, one writer and independent review as a repeatable flow;
- want your language, tone and company tools in private layers, not in a fork.

**Probably not, if you:**
- only run short throwaway scripts with an agent;
- need Windows (macOS first, Linux for the guard, installer and tests);
- expect a security boundary from the guard alone: it is a seatbelt, and the OS sandbox is the wall (see Limits).

## Install
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
| `<yours>/` | Optional: language, tone, work tools, notes for one repo (`notes/*.md` are linked to `~/ai-notes/`). |

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
  A command that asks to leave the sandbox is off by default (`sandbox.allow_unsandboxed_commands`); when on, each exit still asks with a `🔴 high risk` label.

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
| OS-level wall | native `sandbox`: secrets, network, writes | ❌ (rules + guard only) | ❌ |
| Protect its own rules | `Edit` asks for OK + sandbox `denyWrite` | `edit` asks for OK + guard | ❌ |
| Models | `tier` → opus / sonnet / haiku + `effort`; subagents without a tier (`general-purpose`) run on Sonnet | `tiers.json` → any provider | — |

## Structure
| Path | What it is |
|---|---|
| `core/AGENTS.md` | Generic instructions: limits, way of working, tools |
| `core/agents/` | `flow-ticket`, `sub-review`, `sub-builder`, `sub-tester`, `leaf-verify`, `meta-setup` |
| `core/skills/` | `ticket-flow`, `pr-review-ticket`, `session-handoff`, `validate`, `setup-commit`, `grillme` |
| `core/policy.json` | Permissions, single source |
| `core/guard/` | Shared allow / ask / deny logic and the layer loader |
| `adapters/` | Per-tool hooks, plugins and settings. Claude: guard hook, a context-size notice hook (info only, above 150k tokens) and `usage_report.py` (local usage summary and guard log counts, sends nothing) |
| `tests/` | Guard, layers, bootstrap and a full install into a temporary home. Layers used in tests are in `tests/fixtures/layers` |
| `docs/` | `cheatsheet.html` (visual summary, English and Spanish) and `ANALISIS.md` (what is met and what is missing) |
| `build/` | Generated by the installer. Do not edit |

## Agents
| Agent | Role | Writes |
|---|---|---|
| `flow-ticket` | Orchestrates a whole ticket with the `ticket-flow` skill. Main session | only plans in `~/handoffs` |
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

Third-party skills are not bundled, to keep their licenses and updates with their authors. Two that pair well with `ticket-flow`:
```bash
./add-skill.sh https://github.com/obra/superpowers skills/systematic-debugging
./add-skill.sh https://github.com/mattpocock/skills skills/engineering/tdd
```

## Backup
Your layers are in your own repo: commit and push there. `./backup.sh [--without <folder>] [target]` makes a verified zip of this
folder in `~/Downloads`; layers kept in another folder are not in it.

## Changing something
1. Edit `core/…` or `adapters/<tool>/…`  2. `./install.sh`  3. Commit.
Options: `./install.sh --tools claude,opencode` · `--dry-run` · `--home <dir>` (install into another folder, to test).

## License
MIT. See `LICENSE`.
