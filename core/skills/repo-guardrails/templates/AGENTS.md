<!-- Target: under 60 lines, ceiling 300. Real data only; delete any section with nothing real to say. -->
# AGENTS.md

<One line: what this project is, language and framework.>

## Commands
- Done = this is green: `<exact verify command>`
- <Anything that must run in a special way: env vars, outside a sandbox, from a folder.>

## Layout (`<source root>/`)
- `<dir>/`: <what lives here and the one rule about it.>
- `<dir>/`: <...>

## Invariants (E = enforced by a test)
- E: <rule>. Why: <one phrase>.
- <rule not yet enforced>. Why: <one phrase>.
- Never turn a red test green by loosening the assertion or skipping the test.

## Boundaries
- <Do not do X unless asked.>
- No new dependencies without asking.
