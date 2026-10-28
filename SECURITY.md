# Security policy

## What this project protects
ai-setup configures AI coding agents to ask before anything hard to undo (push, deleting files, reading SSH or cloud credentials).
The guard (`core/guard/guard.py`) reads shell text with regexes. It is a seatbelt, not a wall: the known gaps (base64,
commands built inside a script) are listed in `tests/test_guard.py` (`KnownGaps`). The real wall is the OS sandbox that
Claude Code receives from the same `policy.json`. OpenCode has no OS sandbox, only the rules and the guard.

## Reporting a vulnerability
Please report privately through GitHub: **Security → Report a vulnerability** on this repository.
Do not open a public issue for a bypass of the guard or the policy.

Useful in a report: the command or input, the tool and version, the decision you expected (`ask` / `deny`) and the one you got.
You can expect a first answer within 7 days.

## Scope
- In scope: bypasses of `deny` / `ask` rules that are not already listed in `KnownGaps`, installer behavior that overwrites
  or exposes user files, and policy composition bugs that let a layer weaken `core/`.
- Out of scope: the gaps already listed in `KnownGaps`, and vulnerabilities in Claude Code, OpenCode or Codex themselves.

## Supported platforms
macOS is the supported platform. Ubuntu is the blocking CI gate; the macOS run (`ci-macos.yml`) is informational only.
