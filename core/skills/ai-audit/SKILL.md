---
name: ai-audit
description: Score a repo against 8 generic practices (independent review, tests tied to intent, enforced rules, static checks, shared knowledge, small changes, CI, human gate) and list AGENTS.md rules whose `until` date has passed. Read-only. Use for "audita este repo", "cómo vamos con las prácticas de IA", "revisa las reglas vencidas", "ai-audit", "audit this repo", "which rules expired", or as the monthly check. Also lists stale folders in the scratch zone.
---

# ai-audit

Read-only scorecard for one repo. It prints to stdout and writes nothing in the repo.

## Run

```
python3 -I {{AI_SETUP}}/core/skills/ai-audit/audit.py <repo> [--today YYYY-MM-DD] [--projects-dir DIR] [--dev-root DIR]
```

| Option | Default | Use |
|---|---|---|
| `--today` | the current date | Date to compare `until` dates with |
| `--projects-dir` | `~/.claude/projects` | Where the session logs live (practice 1) |
| `--dev-root` | env `AI_AUDIT_DEV_ROOT`, else the layers' `dev_root` (`~` if none) | Folder with `reviews/<repo>/` and `handoffs/*/criteria.md` |

Redirect the output if you want to keep it (for example into `<dev root>/reviews/`), never into the repo. It does not fix anything.

## Read the scorecard

Columns: `#`, `Practice`, `Score`, `Evidence`. The same 8 practices always appear in this order:

| # | Practice | Looks at |
|---|---|---|
| 1 | Independent review | sessions that called `sub-review` vs all sessions; review reports |
| 2 | Tests tied to intent | a `criteria.md` and test files named after criteria |
| 3 | Enforced rules | `AGENTS.md` rules marked `E:` or `(until YYYY-MM-DD)` |
| 4 | Real static checks | a linter configured and installed; disable comments for a tool that is missing |
| 5 | Shared knowledge | `docs/decisions/*.md` and `AGENTS.md` |
| 6 | Small changes | merged PRs above 400 changed lines (first-parent diff vs parent 1); per commit when the default branch has no merge commits, e.g. squash merges |
| 7 | CI covers what matters | `.github/workflows/*` runs tests and e2e |
| 8 | Human gate | first-parent commits on the default branch that came through a PR |

- Score is 1 to 5, or `n/a` when the data is missing (no session logs, no git). `n/a` is not a failure: the evidence column says why.
- Evidence cites `file:line` where a line exists, otherwise a count or a path.
- Scores are heuristics, a conversation starter, not a grade. Read the evidence before acting on a number.
- Rules past their date are listed under the table as `expired: test it or delete it - AGENTS.md:<line>: <rule>`. Turn each one into a test (`E:` rule) or delete it.
- A malformed date (`until 2026-13-45`) is listed as `invalid date: AGENTS.md:<line>: <rule>` and counted in the evidence, never ignored.
- Session logs are matched by the repo folder name as the tail of the project folder; in a git worktree the main repo's name is matched too.

## Old scratch check (read-only)

Besides the scorecard, look for stale folders in `{{DEV}}/_scratch/`. Threshold: **14 days** without changes (change the number here to tune it).

```
find {{DEV}}/_scratch -mindepth 1 -maxdepth 1 -type d -mtime +14
find {{DEV}}/_scratch/<topic> -type f -mtime -14 -print -quit
```

Age means the newest file inside, not the folder's own mtime: if the second command prints anything, the folder is active and is not stale.

- Skip `reviews/` and `handoffs/` (deliverables) and never list the `_scratch/` root.
- For each folder show: folder, age in days, size (`du -sh <path>`), has `.git`? (`test -d <path>/.git`).
- Table of at most 5 rows. With more, a 3-line summary and `+N more`.
- For folders with `.git`, same warning as the `setup-commit` cleanup: `git -C <path> status --short` (dirty) and `git -C <path> log @{u}..` (unpushed; no upstream = unpushed). Show the warning in the table and leave dirty or unpushed clones out of the block.
- Read-only: this check never deletes. Print one copyable block with literal paths (no variables, no `$(...)`, no globs):
  ```
  ! rm -rf {{DEV}}/_scratch/<topic>
  ```
- No stale folders: one line, `Old scratch: none`.

## After the audit

Pick the one or two lowest scores with real evidence and propose a fix as a separate change. A repeated mistake becomes an `E:` rule with a test, or a template change in `core/skills/repo-guardrails/templates/` (see `meta-setup`).
