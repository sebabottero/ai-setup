---
name: validate
description: Run the current repository's real checks (format, build, tests, docs checks) and report a receipt, without fixing anything. Use for "run the checks and the build", "validate again", "is it ready for the PR?", "pasa los checks y el build", "vuelve a validar", "¿está listo para el PR?", or before opening or updating a PR.
---

# Validate the repo

1. Find the repo's checks, in this order:
   - project notes (see "Notes per project" in the global instructions);
   - the repo's CLAUDE.md / AGENTS.md;
   - CI: `.github/workflows/*` and the like;
   - `package.json` (scripts), `Makefile`, `*.slnx`.
2. If the tool has subagents, delegate the run to the `leaf-verify` agent. If not, run them yourself without modifying files.
3. Run whatever is independent in parallel. No auto-fix flags.
4. Deliver the receipt:

| Check | Command | Result | Notes |
|---|---|---|---|

- **Failures:** the first relevant lines + file:line.
- **Not run:** which one and why (tool missing, service down).
- **Ready for PR?** yes / no.

If something fails, do not fix it: ask whether the session that writes the code should do it.
