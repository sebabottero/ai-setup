---
name: setup-commit
description: Close a change in a repo safely - list what this session touched, update docs, run tests, and commit only those paths after explicit approval, never pushing. Use for "commitea esto", "cierra el cambio", "prepara el commit", "commit this", "wrap up this change", or after editing ai-setup.
---

# Close a change with a safe commit

1. `git status --short`: list only the files this session changed; ignore the rest (they may belong to another session).
2. If skills, hooks, agents, MCP or policy changed: update `docs/cheatsheet.html`. Do not read it whole:
   `grep -n` the section and edit only that piece, in both `data-l="es"` and `data-l="en"` where both exist.
3. Run the repo's tests (in ai-setup: `tests/`).
4. If `build/AGENTS.md` or other generated output is out of date, tell the user to run `./install.sh` (do not work around the sandbox if it blocks it).
5. Propose the commit message **in English** and wait for explicit OK.
6. After the OK: `git add <concrete paths>` (never `-A` or `.`) and `git commit`.
7. Never push: show `git remote -v` and stop.
