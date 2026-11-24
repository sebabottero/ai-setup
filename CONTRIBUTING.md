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
- **Update the docs** that mention the thing you changed (`README.md`, `docs/cheatsheet.html`). Every change to ai-setup (rules, agents, skills, policy) updates the cheatsheet in the same commit.
- **No secrets** in code, tests or fixtures.

## README and GitHub About
The README sells the repo to a stranger in under a minute. `tests/test_readme.py` checks the mechanical parts.
- **Order:** title and badges · one benefit line + one line of promise · demo GIF · Why use it · Quick start · What you get · Is it for you? · Limits · Documentation · License.
- **Length:** at most 90 lines. Mechanism, long how-tos and measurements go to `docs/REFERENCE.md`; the README links to them.
- **Tone:** benefit before mechanism. The lead is what the user gains ("work fast, without handing it the keys"), not the category.
- **Proof:** no number without the command that produced it; the GIF shows real output of the tool, never a simulated result.
- **Layers:** each `done` layer links a path that exists; a layer without evidence is `partial` and says what is missing.
- **Same commit:** if the README wording changes, `docs/cheatsheet.html` gets the same wording.
- **GitHub About** (a tracker write: only with the owner's explicit OK). It leads with the same benefit as the README and stays under 350 characters. Current text:
  `Let your AI coding agent work fast, without handing it the keys: a permission guard that asks before the irreversible, one policy for Claude Code, OpenCode and Codex, plus ticket flow, independent review and usage logs.`
  Topics: `agent-skills`, `ai-agents`, `claude-code`, `codex`, `developer-tools`, `llm`, `opencode`, `sandbox`, `agents-md`, `guardrails`, `cost-optimization`, `token-usage`, `code-review`, `harness-engineering`, `observability`.

## Pull requests
Open one PR per change. Say what it does, what it does not cover, and how you tested it. Link the issue if there is one.

## Reporting a problem
Use the issue templates. For a guard bypass, include the exact command and the decision you expected.
