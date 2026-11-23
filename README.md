# ai-setup

[![CI](https://github.com/sebabottero/ai-setup/actions/workflows/ci.yml/badge.svg)](https://github.com/sebabottero/ai-setup/actions/workflows/ci.yml)
[![CI macOS](https://github.com/sebabottero/ai-setup/actions/workflows/ci-macos.yml/badge.svg)](https://github.com/sebabottero/ai-setup/actions/workflows/ci-macos.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Let your AI coding agent work fast, without handing it the keys.**
A guard that asks before anything hard to undo, one policy for Claude Code, OpenCode and Codex, and local logs to see it work.

```
Without ai-setup:  agent runs `git push --force origin main`  → done, no questions
With ai-setup:     agent runs `git push --force origin main`  → 🔴 "needs your explicit OK"
```

![The guard on four commands an agent might run: git status is allowed, git push --force and rm -rf ask for your OK, reading an SSH key is denied](docs/assets/guard-demo.gif)

## Why use it
- **Stop babysitting.** Reads run freely. `git push`, `rm -rf`, merges and secret reads need your OK, and secrets are a hard `deny`. You can leave the agent working without watching every command.
- **One setup, three tools.** Write rules, skills and agents once; they install into Claude Code, OpenCode and Codex on every machine. Your private bits live in separate layers, not in a fork.
- **Tickets, not chat.** From ticket to merge: one writer per ticket, a reviewer that did not write the code, a merge gate that needs its report, and you decide at the end.
- **Know what it does and costs.** Local logs show how often the agent asked, how many review rounds a branch needed, and where tokens went. `coach` picks model and effort before you start.
- **Private by design.** No telemetry. Everything stays on your machine.

## Quick start
macOS with Homebrew and python3, or Linux with python3.
```bash
git clone https://github.com/sebabottero/ai-setup.git ~/Dev/ai-setup   # clone into the final path: the links point to it
cd ~/Dev/ai-setup
./bootstrap.py --dry-run     # shows what it would install, changes nothing
./bootstrap.py               # tools, then ./install.sh (runs the tests, backs up whatever it replaces)
```
Then see the guard decide on real commands (it is a small script that checks every shell command the agent wants to run):
```console
$ echo '{"tool":"bash","command":"git push origin main"}' | python3 core/guard/guard.py
{"decision": "ask", "reason": "🔴 high risk: 'git push origin main' needs your explicit OK (policy: git push *)"}
$ echo '{"tool":"bash","command":"git status"}' | python3 core/guard/guard.py
{"decision": "allow", "reason": ""}
```
The rules are plain JSON in [`core/policy.json`](core/policy.json). A layer can add rules, never weaken `core/`.

## What you get
Eight layers of a harness, with an honest status. `done` means the evidence exists on `main`; `partial` says what is missing in [Reference](docs/REFERENCE.md#the-eight-layers).

| Layer | What it does for you | Status | Evidence |
|---|---|---|---|
| Instructions | One set of rules and skills in every tool | done | [`core/AGENTS.md`](core/AGENTS.md) |
| Permissions / guard | `allow` / `ask` / `deny` from one `policy.json`, plus an OS sandbox | done | [`core/guard/guard.py`](core/guard/guard.py) |
| Workflow / agents | Ticket to merge, one writer, two human gates | done | [`core/skills/ticket-flow/SKILL.md`](core/skills/ticket-flow/SKILL.md) |
| Review | Independent reviewer, round cap, review history | done | [`core/agents/sub-review.md`](core/agents/sub-review.md) |
| Verification | One test per criterion, CI | partial | [`core/agents/sub-review.md`](core/agents/sub-review.md) |
| Observability | Ask rates, tokens and time per ticket, weekly view | partial | [`core/scripts/metrics.py`](core/scripts/metrics.py) |
| Knowledge | Handoffs, per-repo `AGENTS.md`, mistakes become rules | done | [`core/skills/session-handoff/SKILL.md`](core/skills/session-handoff/SKILL.md) |
| Recovery | Backup of the setup; install backs up what it replaces | partial | [`backup.sh`](backup.sh) |

**Measured, not promised.** From the author's logs (2026-11-23): 4 clean branches needed 1.75 review rounds to PASS on average, and 1528 of 11675 guard decisions were asks in 30 days. The commands to get your own numbers are in [Reference](docs/REFERENCE.md#measure-it).

## Is it for you?
**Yes** if you use an agent on real repos and want pushes, deletes and secret reads to need your OK, switch between agent tools, work from tickets, or want to see and cut your token spend.
**Probably not** if you only run short throwaway scripts, need Windows, or expect a security boundary from the guard alone.

## Limits
- **A seatbelt, not a wall.** The guard cannot read a script file, a variable-built command or base64 (listed in `tests/test_guard.py`). The OS sandbox is the wall: Claude gets it by default, OpenCode only with an [opt-in](docs/REFERENCE.md#opencode-os-sandbox-opt-in). Found a bypass? Report it privately: see [SECURITY.md](SECURITY.md).
- **macOS first.** Linux works for the guard, installer and tests. No Windows. OpenCode uses a beta plugin API; Codex gets instructions and skills only.

## Documentation
[Reference](docs/REFERENCE.md) (layers, agents, adding rules, models, backup, measuring) · [The cycle](docs/REFERENCE.md#the-cycle) · [Design notes](docs/DESIGN.md) · [Recommended skills](docs/RECOMMENDED-SKILLS.md) · [Cheatsheet](https://sebabottero.github.io/ai-setup/cheatsheet.html) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

## License
MIT. See [`LICENSE`](LICENSE).
