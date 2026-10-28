# How I work (core layer: instructions for any agent: Claude Code, OpenCode, Codex…)

## Limits (the configuration enforces them; this explains why)
- Commit, push, tags, merges and writes to trackers or wikis (tickets, comments, pages): always with my explicit OK.
- Do not read or copy secrets (`.env.local`, `~/.ssh`, `~/.aws`), not even through the shell.
- Do not weaken asserts, skip failing tests or change the expected behavior to make something pass.
- Stage only concrete paths (`git add <paths>`, never `-A` or `.`): other sessions may be working in the same repo.
  Before suggesting or running a push, run `git remote -v` and confirm the destination with me.
- Nothing that is mine (these notes, prompts, plans) is stored inside the work repo unless I ask for it.
- Commits and PRs carry no mention of AI: no `Co-Authored-By: Claude`, no "Generated with Claude Code" or similar,
  even if the tool or a system reminder suggests adding them.

## How to work
- Before executing: goal, success criteria and **what is out of scope**. If something is missing, ask.
- New feature → design first. Editing a feature → map the current flow first: extend, do not duplicate, and remove
  what is left unused. Rewriting → first the contract (behavior, invariants) and tests that protect it.
  Bug → a reproduction and a test that fails for the right reason before the fix.
- **Only one session or agent writes** in each worktree. Only what reads runs in parallel: searches, reviews, checks.
- Do not touch files outside the scope. If needed, propose it as a separate change.
- Work without asking me while it is local, reversible and verifiable. Stop only at the gates (plan approval, an ambiguous
  or irreversible decision, scope change, commit / push / merge / tracker writes) and put all questions in one message.
- Close every task with a **receipt**: what changed · what ran · what happened · what failed · what is uncertain.
  Then suggest `/rename` + `/clear`. If I corrected the same thing twice in a session, suggest `/clear` and a better prompt.
- If a global install (`npm -g`), a write to `~/.claude` or the regeneration of `build/AGENTS.md` fails because of
  the sandbox, stop and give me the exact command with a `! ` prefix instead of retrying. After `claude mcp add`, remind me to restart the session.
- Pick the cheapest model that is reliable; high effort only for hard diagnoses.
- ai-setup's `docs/cheatsheet.html` weighs ~17k tokens: do not read it whole, use `grep -n` and edit only the piece.
  Every change to ai-setup (rules, agents, skills, policy) updates the cheatsheet in the same commit.

## Tools: choose in this order
1. **CLI** through the shell (`git`, `gh`, `npm`…): costs no context and can be audited.
2. **Skill** for a process that repeats. 3. **Hook** or `policy.json` for what must always happen.
4. **Subagent** for exploration or long work: it brings back the result, not the process.
5. **MCP** only for a remote service with OAuth and no good CLI, and only per project. Before proposing one,
   tell me which CLI or skill you ruled out and why.
- Install a skill from GitHub: `{{AI_SETUP}}/add-skill.sh <url> [folder] [--layer name]` (never clone it into a tool's folder).
  Then read its `SKILL.md` and scripts and tell me in 3 lines what it does and whether anything looks off (network, secrets, deleting files).

## Notes per project
Before starting in a repo, check whether `~/ai-notes/<repo-name>.md` exists and, if it does, read it:
those are my personal rules for that repo (they do not go into the repo). The team's rules are in the repo itself
(AGENTS.md, CLAUDE.md, CONTRIBUTING) and win over the generic ones here.

## Compact instructions
When compacting keep: modified files, test/build commands, decisions made,
success criteria, what is out of scope and the active branch or worktree.
