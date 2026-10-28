---
name: pr-review-ticket
description: Skeptical review of a pull request (or branch) against the ticket it implements - does it cover what the ticket asks, what is missing, what is out of scope, what is risky. Use for "skeptical PR review", "does it meet the ticket?", "what is missing for phase N?", "review escéptico del PR", "¿cumple con lo pedido en el ticket?", "¿qué falta para la fase N?", or before asking for a merge.
---

# Skeptical review of a PR against its ticket

## 1. Requirements (source of truth: the ticket)
- Read the whole ticket, comments included (through the tracker connector or whatever the user gives you).
- If the ticket has phases or a delivery plan, limit the review to the phase named.
- Write the numbered requirements list **before** looking at the code. Mark the ambiguous ones.
- If the reviewer left later feedback, add it as a requirement.

## 2. What the PR does
- Get the branch and the base: `git fetch origin <branch>`, then `git diff --stat origin/<base>...origin/<branch>`.
- If the tool has subagents, delegate reading the diff to the read-only `sub-review` agent with the requirements list.
- For generic code bugs (not tied to the ticket), use the review the tool already ships (Claude Code: `/code-review`) instead of hunting by hand. This skill focuses on requirements, scope and risks.
- Consider only the author's commits if the user asks (`git log --author`).

## 3. Cross-check
| # | Requirement | Status (✅ / 🟡 / ❌) | Evidence (file:line, URL) |
|---|---|---|---|

Then:
- **Out of scope:** changes the ticket does not ask for (files outside the module, CONTRIBUTING, shared config). For each: is it safe? Should it be split into another PR?
- **Risks:** what it can break on develop or for other teams.
- **Pending:** what is missing to close the ticket or the phase. Where to note it: whatever the project rules or notes say.

## 4. Verdict
One line: ready to merge / ready with minor changes / does not meet the ticket. Then the minimal list of changes, ordered by importance.

Be skeptical of your own conclusions too: if something cannot be verified, say so.
