# Contributing

Thanks for helping. Small, focused changes are the easiest to review.

## Run the tests
```bash
python3 -I -m unittest discover -s tests
```
`./install.sh` runs the same tests first and installs nothing if they fail. Use `./install.sh --dry-run` or `--home <dir>` to try a change without touching your real config.

## Where changes go
| You want to change | Edit |
|---|---|
| A generic rule, agent or skill | `core/` |
| How one tool is wired (hooks, plugins, settings) | `adapters/<tool>/` |
| What a command is allowed to do | `core/policy.json` |
| Your own language, tone or company tools | a private layer, not this repo |

## Rules for a change
- **Tests first for the guard.** A new rule needs a test that fails without it. If a case cannot be caught, add it to `KnownGaps` instead of hiding it.
- **Do not weaken a test** to make it pass. If the expected behavior changes, say why in the PR.
- **Nothing personal in `core/`:** no names, company tools or private paths.
- **Update the docs** that mention the thing you changed (`README.md`, `docs/cheatsheet.html`).
- **No secrets** in code, tests or fixtures.

## Pull requests
Open one PR per change. Say what it does, what it does not cover, and how you tested it. Link the issue if there is one.

## Reporting a problem
Use the issue templates. For a guard bypass, include the exact command and the decision you expected.
