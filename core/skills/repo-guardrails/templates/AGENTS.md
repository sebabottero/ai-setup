<!-- Target: under 60 lines, ceiling 300. Real data only; delete any section with nothing real to say. -->
# AGENTS.md

<One line: what this project is, language and framework.>

## Commands
- Done = this is green: `<exact verify command>`
- <Anything that must run in a special way: env vars, outside a sandbox, from a folder.>

## Layout (`<source root>/`)
- `<dir>/`: <what lives here and the one rule about it.>
- `<dir>/`: <...>

## Rules
Every rule is either `E:` (a test fails CI when it breaks) or ends with `(until YYYY-MM-DD)`: by that date, test it or delete it.
- E: <rule>. Why: <one phrase>. Test: `<test name>`.
- <rule not yet enforced>. Why: <one phrase>. (until YYYY-MM-DD)
- Never turn a red test green by loosening the assertion or skipping the test.

## Risk tiers
| Tier | Examples | Review before merge |
|---|---|---|
| Low | Docs, copy, style, a test-only change | Independent reviewer report (a short one is fine) |
| Medium | A feature or bug fix inside one module | Reviewer report checked against `criteria.md`, every criterion has a test |
| High | Data, auth, money, migrations, public API, deletes, >400 lines | Reviewer report + the human reads the diff; split it if it can be split |

Product decisions go in `docs/decisions/NNN-<topic>.md` (copy `000-template.md`).

## Boundaries
- <Do not do X unless asked.>
- No new dependencies without asking.
