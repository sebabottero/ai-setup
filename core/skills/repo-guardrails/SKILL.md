---
name: repo-guardrails
description: Prepare a repo so AI agents keep respecting its architecture - a short AGENTS.md, a one-line CLAUDE.md, architecture tests that fail the build, and a minimal CI. Use for "set up AGENTS.md", "guardrails for this repo", "make the AI respect the architecture", "prepare this repo for agents", "que la IA respete la arquitectura", "prepara este repo para agentes", "guardarraíles para este repo".
---

# Repo guardrails

Make a repo hold its own rules, whatever the language. Offer it, never run it unasked.
Based on blog and practice evidence, **not an official standard**; the only part verified end to end is the file-scan test (step 4).

## Principles
1. A written rule is a suggestion; a rule in a test that fails CI is a barrier. What must hold goes in a test; `AGENTS.md` then mentions it and marks it **E** (enforced). A rule with no test yet carries `(until YYYY-MM-DD)`: by then, test it or delete it, so untested rules cannot erode silently.
2. `AGENTS.md` is the cross-tool standard. Short (target < 60 lines, ceiling 300), concrete, exact commands, a real layout map (not a file listing), invariants **each with a one-phrase reason**, boundaries. No generic advice ("write clean code"), no long "don'ts" without "dos", no auto-generated filler (one study reports ~3% lower success and 20%+ higher cost).
3. `CLAUDE.md` contains only `@AGENTS.md` (one source of truth). Sources disagree on whether Claude Code reads `AGENTS.md` alone: tell the user to verify in a fresh session by asking about a fact that exists only in `AGENTS.md`.
4. `CONTRIBUTING.md` is for humans: do not create it unless asked, and do not rely on agents reading it.
5. Nested `AGENTS.md` only if a subfolder truly has different rules.

## Process (6 steps, one commit each in the target repo; local commit only, no push)
1. **Read and interview.** Detect language and build from marker files (`build.gradle.kts`, `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`…). Find the real verify command (the one CI or the maintainers run) and run it once to see it is green. Then ask the user, **one question at a time, max ~5**, for the real invariants and boundaries ("what must never happen in this codebase, and why?"). Never invent them. Check first whether `AGENTS.md`/`CLAUDE.md` exist: extend, do not overwrite.
2. **`AGENTS.md`** from `templates/AGENTS.md`, filled with real data only. Delete unused placeholders and the length comment. Keep the **Rules** convention (`E:` or `(until YYYY-MM-DD)`) and fill the **Risk tiers** table (low / medium / high → the review each needs) with the user's real examples.
3. **`CLAUDE.md`** from `templates/CLAUDE.md` (`@AGENTS.md`). Tell the user the fresh-session check from principle 3.
4. **Architecture tests, red first.** For each invariant marked E: write the test, temporarily add a violation, see it **fail for the right reason** (message names the rule and the fix), revert, see it green. If today's code already violates the rule, report it and ask; never loosen the rule or add an exemption to pass. Always ask before adding a dependency.
5. **Decisions and PRs.** Copy, only if missing:
   - `templates/decisions/000-template.md` → `docs/decisions/000-template.md`: one short file per product decision (Context · Decision · Why · Alternatives · Date), so decisions live in the repo, not in someone's notes.
   - `templates/.github/pull_request_template.md` → `.github/pull_request_template.md`: every PR links its criteria, maps each criterion to a test, attaches the reviewer report and names its risk tier.
6. **Minimal CI** from `templates/ci-github-actions.yml` → `.github/workflows/test.yml`: pinned action versions, no secrets, test/debug only, same command as the verify command. It includes a step that **warns** (never fails) when a PR changes more than 400 lines, and an optional e2e job, commented, with how to enable it: enable it only if the project has an e2e run that passes locally. It cannot be run locally: tell the user the check is the Actions tab green after they push (you do not push).

## Tool per language (step 4)
| Language | Tool to propose | Status |
|---|---|---|
| Any | Plain test that scans source files with a regex (imports, forbidden words), no new dependency | **Default, proven** |
| Kotlin/Java | JUnit file scan (`examples/kotlin/ArchitectureTest.kt`); ArchUnit or Konsist if the user accepts a dependency | JUnit scan proven; others untested |
| TypeScript | ArchUnitTS, dependency-cruiser, ESLint rules | Untested, verify in a real project |
| Python | import-linter, or a pytest file scan | Untested, verify in a real project |
| Go | golangci-lint, or a `go test` file scan | Untested, verify in a real project |

Language not listed: say so and fall back to the file scan. Never claim an untested row works.

## File-scan recipe (any language)
- Walk the source dir, read each file, flag lines matching a forbidden pattern (e.g. a layer importing a framework) or files outside an allowed list.
- Fail with a message: the rule, the reason, what to do instead, and every `file:line` found.
- Fail loudly if the source dir is missing (a moved folder must not turn the test into a silent pass).
- Run it from the same command as the verify command so CI picks it up.

## Receipt
List each file created or extended, one line each, and say which already existed:
- `AGENTS.md` (Rules convention + Risk tiers) · `CLAUDE.md`
- `docs/decisions/000-template.md` · `.github/pull_request_template.md`
- `.github/workflows/test.yml` (from `ci-github-actions.yml`)
- every architecture test, with the rule it enforces and "seen red, then green".

## Done when
`AGENTS.md` + `CLAUDE.md` + decision and PR templates committed; every E rule has a test seen red then green; CI file added; user knows the two checks left on their side (fresh-session `AGENTS.md` check, Actions tab after push).
