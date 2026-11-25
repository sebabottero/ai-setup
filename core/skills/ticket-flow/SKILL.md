---
name: ticket-flow
description: Run a whole ticket end to end - understand, plan, build, test, docs, validate, review - with one writer in its own git worktree and every read-only stage in parallel, stopping only at human gates. Use for "work ticket PROJ-123", "do the whole ticket", "trabaja el ticket PROJ-123", "hacé todo el ticket", "orquestá", "corré todo en paralelo", "resolvé esto sin que tenga que estar mirando", or when running as the flow-ticket agent.
---

# A ticket end to end, with minimal supervision

## Map
```
0 Contract ► Understand ──► 1 Plan ──► ⛔ GATE 1 ──► 2 Build (one writer, one worktree) ──► 3 Validate ‖ Review ──► ⛔ GATE 2
   ‖ Explore x N            + critic     bug: sub-tester first                       leaf-verify ‖ sub-review
```
After the PR: `4 Post-PR re-review` (`sub-review` on the commit vs `criteria.md`), then the comment OK at Gate 2.
`‖` = in parallel, in the same turn. Small tasks skip stages: say which ones and why.

## Rules
- **Only what reads runs in parallel**: exploration, reading the ticket, reviews and checks. Launch them in a single message.
- **One writer** per ticket, in one worktree. Writing in parallel produces clashing decisions; if the ticket is so big it
  asks for several writers, split it into tickets and tell me at Gate 1.
- Worktree: if you are already in one (a workspace is already a worktree: `git rev-parse --git-dir` ≠ `--git-common-dir`), that is
  the ticket's; do not create another. If not: `git worktree add <dev root>/worktrees/<repo>/<ticket> -b ai/<ticket> <base>` and pass
  that path as the only working directory.
- The ticket branch stays local until Gate 2. No intermediate commits: the policy asks for OK on every commit.

## Run record
`<dev root>/handoffs/<ticket>/run.json` is the journal of the run: session ids, branch, PR number, review reports and rounds (stage, verdict), start and end time. It is for reading afterwards: nothing resumes from it.
Write it only with `python3 -I {{AI_SETUP}}/core/guard/run_json.py update <ticket> [--session ID] [--branch B] [--pr N] [--round STAGE:VERDICT[:REPORT]] [--report PATH] [--cross-review on|off] [--end]` (first call creates it; every call adds, never rewrites). Pass `--session auto`: it reads the session id the SessionStart hook stored for the current folder (with none stored it records nothing and says so).
Call it at: 0a after my OK (`--session auto`, `--branch`), Gate 1 after my OK (`--session auto`, and `--cross-review on|off` for my cross-provider choice), each stage 3 and stage 4 review (`--round 3:<verdict>:<report path>`, `--round 4:...`), the PR (`--pr N`) and the end of stage 4 (`--end`). The same on the short route. A failed call never stops the ticket: say so in the receipt.

## Short route (low risk)
Read the repo's `AGENTS.md` section "Risk tiers" and propose tier low when the change fits it (a style fix, a typo).
I confirm in one line. Then skip exploration and planning, but still run `sub-review` and write the report with the same
helper and path as `sub-review` (`python3 -I {{AI_SETUP}}/core/guard/review_report.py`, `<dev root>/reviews/<repo>/<branch>.md`; `header` keeps earlier rounds as `.r<N>.md`, then `log --stage 3` appends to `reviews.log`).
`sub-tester` still runs, one test per criterion, as in the full flow.
Any other tier, no confirmation, or a repo with no "Risk tiers" section: the full flow below.
The 0a scope contract still applies in short form: allowlist and out of scope in one line, confirmed together with the tier,
and written into `criteria.md` (there is no `plan.md` on this route).
The short route still needs `criteria.md`; a 1-3 line version (Goal + 1-3 Given/When/Then) is enough. If there is none, stop and offer `grillme`
(for a low-risk change, ask it for the short form: Goal + 1-3 criteria), as at Gate 1: that rule applies to both routes.

## 0a · Scope contract (before planning or writing)
If `criteria.md` has `## Slices`, first pick slice K (see "With slices" below): everything in this contract covers only slice K.
Read the ticket and the latest stakeholder feedback (comments, review). Emit:
- **(a) Allowlist:** files and directories that may be touched.
- **(b) Remove or avoid:** content the stakeholders ask to take out, quoted verbatim.
- **(c) Not touched:** what stays out.
- **(d) Success criteria:** taken from `criteria.md`, never reworded. If there is no `criteria.md`, stop here and offer `grillme`, the same rule as Gate 1.
- **(e) "My commits":** if the request refers to them, filter with `git log --author=<me>`.

If any of the five is missing, or the request is vague or ambiguous, use the `grillme` skill (one question at a time) before going on.
If it is complete, show the contract and **wait for my OK** (gate). Save it at the top of `plan.md`.
**View of the contract.** Read the preference with `python3 -I {{AI_SETUP}}/core/guard/render_gate.py --prefs`; if that fails or prints nothing, treat it as `gate_view=md`. With `gate_view=html`, before showing the contract run `python3 -I {{AI_SETUP}}/core/guard/render_gate.py --check <criteria.md> || python3 -I {{AI_SETUP}}/core/guard/render_gate.py <criteria.md>` (check the page is fresh, re-render when it is not), then show the contract in chat as above plus `! open <absolute path to criteria.html>`. The short route (no `plan.md`) uses `criteria.html` only. With `gate_view` `md`: no `.html` is written and the gate is unchanged.
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
- risks and open questions;
- a **criteria map**: each criterion → the step(s) and test that cover it; a step with no criterion is extra scope: drop it, or list it under "extras" in the Gate 1 summary.

**Plan critic.** Full route only. Before Gate 1, one `sub-review` (read-only, one round) attacks `plan.md` with a fixed question: what breaks, what is missing, what is extra?
Its input is `plan.md`, `criteria.md` and the 0a contract (there is no diff yet); it returns its findings as its message and skips the report step (step 5), so nothing is written at the review report path the merge gate reads. The orchestrator always saves that text to `<dev root>/handoffs/<ticket>/plan-critic.md` (the critic stays read-only and writes no file).
Fix what it finds yourself, but only inside the 0a contract and `criteria.md`; a fix that would change either is unresolved.
Gate 1 mentions the critic only for unresolved findings.

**Split signal.** One strong signal (mixed topics such as refactor + behaviour change, or >400 lines estimated) or two weak ones (several modules or layers, independently testable criteria): propose a split into several PRs. Below ~150 estimated lines it is always a single PR, with no discussion.
**With slices.** If `criteria.md` has `## Slices`, the user names slice K in the run's args (default: the first slice not yet merged); its build covers only slice K's criteria: the 0a contract and its allowlist (K is chosen first, at 0a), the plan, the writer's allowlist and the review.
If Gate 1 recommends a split and `criteria.md` has no `## Slices`, you write that section (criteria numbers per PR, with dependencies) into `criteria.md` right after my OK, before 0a; the build then runs slice 1.

## ⛔ GATE 1: plan approval
Needs `<dev root>/handoffs/<ticket>/criteria.md` on both routes (short route: the 1-3 line version). If there is no criteria.md, stop and offer the `grillme` skill, which writes it.
A single message: plan summary (short and scannable) + **all** the questions together. Build nothing until the OK.
**View of the plan.** Read the preference with `python3 -I {{AI_SETUP}}/core/guard/render_gate.py --prefs`; if that fails or prints nothing, treat it as `gate_view=md`. With `gate_view=html`, first write the questions, the unresolved critic findings and the extras into `plan.md` "Risks / open questions", then run `python3 -I {{AI_SETUP}}/core/guard/render_gate.py --check <plan.md> || python3 -I {{AI_SETUP}}/core/guard/render_gate.py <plan.md>` (check the page is fresh, re-render when it is not) before showing the gate. The message is then at most 3 lines plus the open line: line 1 the verdict line (`Single PR ...` or `Split into N ...`); line 2 the questions (their count, "answers in chat"; the questions themselves are in `plan.md` "Risks / open questions" and so in the view); line 3 the cross-provider review line when the tier is high, otherwise the unresolved critic findings and extras in a few words; when line 3 is the cross-provider review line, line 2 also says the unresolved critic findings and extras are in `plan.html` (a few words); then `! open <absolute path to plan.html>`. The short route has no `plan.md`: it shows `criteria.html` from 0a and keeps its gate as it is. With `gate_view` `md`: no `.html` is written and the gate is unchanged.
**Scoped approvals for protected paths (after my OK, before 2 · Build).** Only in this repo's own ticket worktrees (`<dev root>/worktrees/<repo>/<ticket>`). Take the allowlist paths that `policy.json` `protected_paths` covers and give me, in one message, this line for me to run (exact relative paths, no globs): `! python3 -I {{AI_SETUP}}/core/guard/scope.py add <worktree> <path>...`. I run it, not you: it writes `~/.ai-setup/scopes/`, which the sandbox does not let a command write, and the guard asks about any other form of that script. Wait for it, then check with `python3 -I {{AI_SETUP}}/core/guard/scope.py show <worktree>`. Edits to exactly those paths then ask once (a grant lasts 12 h); every other protected path asks every time. If the plan needs a protected path that is not in the allowlist (so not in the scope), stop and ask me: do not widen the scope yourself. No protected paths in the allowlist, or a workspace outside `<dev root>/worktrees`: skip this step and say so.
It always carries one verdict line with your recommendation: `Single PR (~N lines, 1 topic)` or `Split into N: signals X, Y`. My OK at Gate 1 accepts it, with no separate question. The default is one slice per run; mention the alternative only when you recommend it. A slice waits for another to be merged only if it depends on its code.

**Cross-provider review (opt-in, high tier only).** Read the ticket's tier from the repo's `AGENTS.md` "Risk tiers". Only when it is **high**, Gate 1 carries one more line, `Cross-provider review: off (default) - say "cross-review" to add a second reviewer from another model provider (Codex or OpenCode with a non-Claude model)`. Any other tier, or no tier: no line, no question, nothing changes. The default is off: it runs only if I answer "cross-review" at Gate 1; silence or a plain OK means off. Record the choice with `run_json.py update <ticket> --cross-review on|off`.

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
- `sub-review` on the diff against `plan.md` (and the `pr-review-ticket` skill if there is a ticket). It still compares against `plan.md`; its brief gives the exact `log --stage 3` command so the round is logged with that stage;
  stage 4 re-reviews the committed change against `criteria.md`. The two reviews cover different angles: plan (stage 3) vs criteria (stage 4).
- If something fails: back to the writer, fix and validate again. **At most 2 rounds**; if it still fails, stop at the gate.
- **Round cap (stages 3 and 4).** After each round, run `python3 -I {{AI_SETUP}}/core/guard/review_report.py rounds --dir <worktree> --stage <3|4>`.
  It prints `stage=N rounds=R open=O stop=yes|no`, read from `reviews.log`. If the branch still has `blocking` or `major` findings after 2 review rounds in one stage (`stop=yes`), do not start round 3: ask me at the next gate what to do, showing the open findings and their triage.

**Cross-provider review (only when I opted in at Gate 1).** In the same turn as `sub-review`, in stage 3 and again in stage 4, the orchestrator launches a second reviewer on the same diff (the same range, plan or `criteria.md` as `sub-review`, with the same brief and no copy of its report). It is read-only: it edits nothing and writes no file, its final message is the report. Two ways, in the ticket's worktree, with a non-Claude model (`<provider>` = `codex` or `opencode`, the report name):
The brief goes in a file, `<dev root>/handoffs/<ticket>/xprov-brief.md` (written with the Write tool), and the prompt reaches the tool from a file or stdin, never as a quoted argument: the agent text has backticked spans (`git commit`, `git diff <base>...<head>`) that the shell would run before the tool starts.
- Codex: `cat {{AI_SETUP}}/core/agents/sub-review-xprov.md <brief file> | codex exec --sandbox read-only -` (`-` makes Codex read its instructions from stdin; confirmed in `codex exec --help`);
- OpenCode: `opencode run --agent sub-review-xprov --model <non-claude provider/model> --file <brief file> "Review as the attached brief says."` (the installed agent has `edit: none` and read-only shell). `--model` is mandatory and must be a non-Claude model: without it the agent runs on the session's model; otherwise it is not a second provider.
**These launch commands are not verified end to end**: the flags come from the CLIs' help and general knowledge and were not run in a real ticket. If one fails, report it in the receipt and fall back to `sub-review` alone; do not guess other flags.
These commands are not on the policy's allowlists: each one asks for my OK like any other command; nothing here widens the policy. If the tool is not installed or I decline, say so in the receipt and carry on with `sub-review` alone.
The orchestrator saves that message as the second report: it runs `python3 -I {{AI_SETUP}}/core/guard/review_report.py header --dir <worktree> --reviewer <provider>` (first line = the path `<dev root>/reviews/<repo>/<branch>.<provider>.md`; then the header block, which it puts at the top) and writes the file with the Write tool. In OpenCode, saving the second report asks for OK each time: `flow-ticket` only edits under `handoffs/*`, and the agent is not widened for this. A report from an earlier stage is first kept as `<branch>.<provider>.r<N>.md` by the same `header` call (stage 4 leaves the stage 3 one there). The merge gate's `<branch>.md` is not touched and no `sub-review` round is archived: `sub-review`'s report and the second one are both kept. Do not run `log` or `rounds` for it, and it does not count for the round cap. Pass the path to `run_json.py update <ticket> --report <path>`.
At Gate 2 show both verdicts and both issue tables side by side; a `blocking` or `major` finding from either one stops like `sub-review`'s. Nothing is fixed on its own.

## ⛔ GATE 2: handover
A single message with:
1. **Receipt:** changes made · commands run · their outcome · failures · open doubts.
2. Acceptance criteria: ✅ / 🟡 / ❌ with evidence.
3. Draft PR description. Before drafting, read the repo's PR template (`.github/pull_request_template.md`) and fill every section; if none exists, use the format of earlier PRs. Use your writing skill if you have one.
4. Pending items and extras found, split into "in scope" and "extras".
5. What you need from me: commit + push + PR + tracker (the config will ask for OK on each).

After the OK: commit on the ticket branch or the one I name, push, PR (body from the repo's PR template, every section filled; no template: the format of earlier PRs). Then run stage 4 below; the worktree stays until it is done.

## 4 · Post-PR re-review
Once the PR exists (full or short route), run `sub-review` on the committed change against `criteria.md` (only slice K's criteria when it has `## Slices`).
Write its report with `python3 -I {{AI_SETUP}}/core/guard/review_report.py` so the tree hash matches the commit.
The report path is the same `<dev root>/reviews/<repo>/<branch>.md`: it overwrites the stage 3 report (intended; the merge gate reads the newest), but `header` first keeps that one as `<branch>.r<N>.md`. The brief gives the exact command `python3 -I {{AI_SETUP}}/core/guard/review_report.py log --dir <worktree> --stage 4` to run once the report is written (the one thing the brief carries besides the three items below).
- Short route (tier low): the same re-review applies against the 1-3 line `criteria.md`.
- Apart from that command, the brief carries only the commit, the path to `criteria.md` and the report path, plus "slice K" as a scope pointer when `criteria.md` has `## Slices`; no summary of what was built or what passed.
- blocking or major: stop and show it. I decide whether a fix commit goes in the same PR; nothing is fixed or pushed on its own.
  A fix commit in the same PR makes the report's Tree stale, so stage 4 re-runs on the new commit before posting.
  This is the one exception to "no intermediate commits": a stage 4 fix commit the user approves.
- When the result is ready, ask my OK at Gate 2 to post it as a comment on the PR, with `gh pr comment` and only after my OK.
  Nits go in that comment and do not block.
  The round cap of stage 3 applies here too: run `review_report.py rounds --stage 4` before re-running the review; on `stop=yes` ask me at the next gate instead.
  The result and this OK arrive in a follow-up Gate 2 message after the PR; that ask is part of Gate 2.
- Only after stage 4 is done (and any fix-commit decision), if you created the worktree, delete it (leave alone any worktree a workspace manager created). Before deleting it, if a scope was added, give me `! python3 -I {{AI_SETUP}}/core/guard/scope.py clear <worktree>` to run (it asks; an unused scope also expires by itself).

## Running unattended
- One workspace (one worktree) per ticket with the `flow-ticket` agent (Claude Code or OpenCode).
- How to launch it in each tool in the terminal: ai-setup README, section "Adapters".
- Between gates ask for nothing: what is local, reversible and verifiable just gets done.
- **Stop and ask** if a new permission is needed, the scope changes, the expected behaviour is unclear or something would have an external effect.
