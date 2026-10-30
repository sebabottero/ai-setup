# How I work (core layer: instructions for any agent: Claude Code, OpenCode, Codex…)

## Limits (the configuration enforces them; this explains why)
- Commit, push, tags, merges and writes to trackers or wikis (tickets, comments, pages): always with my explicit OK.
- Do not read or copy secrets (`.env.local`, `~/.ssh`, `~/.aws`), not even through the shell.
- Never turn a red check green by loosening an assertion, skipping the test or redefining the expected result.
- Stage only concrete paths (`git add <paths>`, never `-A` or `.`): other sessions may be working in the same repo.
  Before suggesting or running a push, run `git remote -v` and confirm the destination with me.
- Nothing that is mine (these notes, prompts, plans) is stored inside the work repo unless I ask for it.
- Commits and PRs carry no mention of AI: no `Co-Authored-By: Claude`, no "Generated with Claude Code" or similar,
  even if the tool or a system reminder suggests adding them.

## How to work
- Before executing: goal, success criteria and **what is out of scope**. If something is missing, ask. For a big task
  (a ticket, a setup change) ask at most 5 scope questions in ONE message: repo and remote, in / out of scope,
  generic or project-specific, done criteria.
- New feature → sketch the design before any code. Changing an existing one → trace how it works today, extend that
  path instead of adding a second one, and delete what ends up unused. Rewrite → pin down the behavior and invariants
  first, with tests that guard them. Bug → reproduce it with a test that fails for the right reason, then fix.
- **Only one session or agent writes** in each worktree. Only what reads runs in parallel: searches, reviews, checks.
- Do not touch files outside the scope. If needed, propose it as a separate change.
- Work without asking me while it is local, reversible and verifiable. Stop only at the gates (plan approval, an ambiguous
  or irreversible decision, scope change, commit / push / merge / tracker writes) and put all questions in one message.
- Close every task with a **receipt**: changes made · commands run · their outcome · failures · open doubts.
  Add the changes of medium or high risk (tests, hooks, policy, install scripts), each with one line on its impact.
  Then add **Efficiency** (3-5 lines, only if something concrete could have gone better in this session, else "nothing to adjust"):
  what in my prompt or in the model / effort choice caused rework, and how to ask it next time. Never generic tips.
  Then suggest `/rename` + `/clear`. If I corrected the same thing twice in a session, suggest `/clear` and a better prompt.
- If something is still blocked by the sandbox (a write to `~/.claude`, the regeneration of `build/AGENTS.md`), do not
  retry and do not interrupt me per step: keep working, collect every blocked command and give them to me at the end
  of the task in ONE copyable block, each with a `! ` prefix. After `claude mcp add`, remind me to restart the session.
- Start with the lowest-cost model that does the job dependably; reserve high effort for hard diagnoses.
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
Before starting in a repo, check whether `{{DEV}}/ai-notes/<repo-name>.md` exists and, if it does, read it:
those are my personal rules for that repo (they do not go into the repo). The team's rules are in the repo itself
(AGENTS.md, CLAUDE.md, CONTRIBUTING) and win over the generic ones here.

## Compact instructions
When compacting keep: modified files, test/build commands, decisions made,
success criteria, what is out of scope and the active branch or worktree.
