---
name: ticket-flow
description: Run a whole ticket end to end - understand, plan, build, test, docs, validate, review - with one writer in its own git worktree and every read-only stage in parallel, stopping only at human gates. Use for "work ticket PROJ-123", "do the whole ticket", "trabaja el ticket PROJ-123", "hacé todo el ticket", "orquestá", "corré todo en paralelo", "resolvé esto sin que tenga que estar mirando", or when running as the flow-ticket agent.
---

# A ticket end to end, with minimal supervision

## Map
```
0 Contract ► Understand ──► 1 Plan ──► ⛔ GATE 1 ──► 2 Build (one writer, one worktree) ──► 3 Validate ‖ Review ──► ⛔ GATE 2
   ‖ Explore x N                         bug: sub-tester first                       leaf-verify ‖ sub-review
```
`‖` = in parallel, in the same turn. Small tasks skip stages: say which ones and why.

## Rules
- **Only what reads runs in parallel**: exploration, reading the ticket, reviews and checks. Launch them in a single message.
- **One writer** per ticket, in one worktree. Writing in parallel produces clashing decisions; if the ticket is so big it
  asks for several writers, split it into tickets and tell me at Gate 1.
- Worktree: if you are already in one (an Orca workspace is one: `git rev-parse --git-dir` ≠ `--git-common-dir`), that is
  the ticket's; do not create another. If not: `git worktree add <dev root>/worktrees/<repo>/<ticket> -b ai/<ticket> <base>` and pass
  that path as the only working directory.
- The ticket branch stays local until Gate 2. No intermediate commits: the policy asks for OK on every commit.

## Short route (low risk)
Read the repo's `AGENTS.md` section "Risk tiers" and propose tier low when the change fits it (a style fix, a typo).
I confirm in one line. Then skip exploration and planning, but still run `sub-review` and write the report with the same
helper and path as `sub-review` (`python3 -I {{AI_SETUP}}/core/guard/review_report.py`, `<dev root>/reviews/<repo>/<branch>.md`).
`sub-tester` still runs, one test per criterion, as in the full flow.
Any other tier, no confirmation, or a repo with no "Risk tiers" section: the full flow below.
The 0a scope contract still applies in short form: allowlist and out of scope in one line, confirmed together with the tier,
and written into `criteria.md` (there is no `plan.md` on this route).
The short route still needs `criteria.md`; a 1-3 line version (Goal + 1-3 Given/When/Then) is enough. If there is none, stop and offer `grillme`
(for a low-risk change, ask it for the short form: Goal + 1-3 criteria), as at Gate 1: that rule applies to both routes.

## 0a · Scope contract (before planning or writing)
Read the ticket and the latest stakeholder feedback (comments, review). Emit:
- **(a) Allowlist:** files and directories that may be touched.
- **(b) Remove or avoid:** content the stakeholders ask to take out, quoted verbatim.
- **(c) Not touched:** what stays out.
- **(d) Success criteria:** taken from `criteria.md`, never reworded. If there is no `criteria.md`, stop here and offer `grillme`, the same rule as Gate 1.
- **(e) "My commits":** if the request refers to them, filter with `git log --author=<me>`.

If any of the five is missing, or the request is vague or ambiguous, use the `grillme` skill (one question at a time) before going on.
If it is complete, show the contract and **wait for my OK** (gate). Save it at the top of `plan.md`.
After that, every edit or writer brief rejects files outside the allowlist and proposes them as a separate change.

## 0b · Understand (parallel)
In the same turn:
- the whole ticket, with comments (through the tracker connector);
- the project notes (`<dev root>/ai-notes/<repo>.md`) and the repo's rules (CLAUDE.md / AGENTS.md / CONTRIBUTING);
- 2 or 3 Explore subagents with narrow questions: where the logic lives, the current flow end to end, existing tests and docs.

Task type: **feature** (design before code) · **edit** (trace today's flow, then extend it, no duplicates) · **bug** (reproduce it before fixing).
If the ticket is vague, use the `grillme` skill before the plan.

## 1 · Plan
Write `<dev root>/handoffs/<ticket>/plan.md` (never in the repo):
- goal in 1 or 2 sentences;
- **acceptance criteria**, each with its concrete check; they come from `criteria.md` (copy them, do not reword). If the two ever differ, `criteria.md` wins;
- **out of scope**;
- the writer's steps, in order, and which files each touches;
- for a feature, the seams to test (`tdd` skill): public interface and what each one covers;
- risks and open questions.

**Split signal.** One strong signal (mixed topics such as refactor + behaviour change, or >400 lines estimated) or two weak ones (several modules or layers, independently testable criteria): propose a split into several PRs. Below ~150 estimated lines it is always a single PR, with no discussion.
**With slices.** If `criteria.md` has `## Slices`, the user names slice K in the run's args (default: the first slice not yet merged); its build covers only slice K's criteria: the plan, the writer's allowlist and the review (also the 0a contract).

## ⛔ GATE 1: plan approval
Needs `<dev root>/handoffs/<ticket>/criteria.md` on both routes (short route: the 1-3 line version). If there is no criteria.md, stop and offer the `grillme` skill, which writes it.
A single message: plan summary (short and scannable) + **all** the questions together. Build nothing until the OK.
It always carries one verdict line with your recommendation: `Single PR (~N lines, 1 topic)` or `Split into N: signals X, Y`. My OK at Gate 1 accepts it, with no separate question. The default is one slice per run; mention the alternative only when you recommend it. A slice waits for another to be merged only if it depends on its code.

## 2 · Build
One writer, the `sub-builder` agent (balanced model; you stay on the strong one for planning and decisions), in the worktree, with a brief made with the `session-handoff` skill:
goal, the contract's allowlist (reject what falls outside), out of scope, how to verify.
- **Bug:** root cause first with the `systematic-debugging` skill. Then `sub-tester` writes the regression test in the worktree and confirms it **fails for the right reason**.
  Then the writer fixes until it passes.
- **Feature / edit:** the writer follows the `tdd` skill (the seams to test go in the Gate 1 plan); then `sub-tester` adds the acceptance-criteria tests in the same worktree.
- **Docs, at the end, by the same writer:**
  - read the repo's docs rules first (CONTRIBUTING, a `/document` command, CLAUDE.md); they win over this;
  - **the code is the authority**: check every endpoint, field or class in the code before writing it down;
  - document what the code does today; what is pending goes where the project notes say (if they say nothing, in the receipt);
  - match the depth and tone of the neighbouring docs and run the docs checks if they exist.

## 3 · Validate ‖ Review (parallel)
- `leaf-verify` on the worktree → checks receipt.
- `sub-review` on the diff against `plan.md` (and the `pr-review-ticket` skill if there is a ticket).
- If something fails: back to the writer, fix and validate again. **At most 2 rounds**; if it still fails, stop at the gate.

## ⛔ GATE 2: handover
A single message with:
1. **Receipt:** changes made · commands run · their outcome · failures · open doubts.
2. Acceptance criteria: ✅ / 🟡 / ❌ with evidence.
3. Draft PR description (in the format of earlier PRs; use your writing skill if you have one).
4. Pending items and extras found, split into "in scope" and "extras".
5. What you need from me: commit + push + PR + tracker (the config will ask for OK on each).

After the OK: commit on the ticket branch or the one I name, push, PR. Then, if you created the worktree, delete it
(Orca manages the ones it created).

## Running unattended
- One Orca workspace per ticket with the `flow-ticket` agent (Claude Code or OpenCode). Orca tells you when the session is waiting.
- How to launch it in each tool without Orca: ai-setup README, section "Adapters".
- Between gates ask for nothing: what is local, reversible and verifiable just gets done.
- **Stop and ask** if a new permission is needed, the scope changes, the expected behaviour is unclear or something would have an external effect.
