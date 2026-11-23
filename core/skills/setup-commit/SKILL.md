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
7. Never push: show `git remote -v`. Do not push; run step 8, then stop.
8. **Cleanup** (also run by hand when the user says "merged" / "mergeado"; there is no merge hook). Never touch the `_scratch/` root, `reviews/` or `handoffs/`.
   1. List only the folders `{{DEV}}/_scratch/<topic>/` this session created: the ones you made or named in this session's receipt or commands. Never infer ownership from mtime alone (a folder's mtime changes whenever any file inside changes, so another session's folder can look new).
      To confirm, compare the birth time: `stat -f %B {{DEV}}/_scratch/<topic>` must be later than the session start (the first action in `{{DEV}}/logs/actions.log` with this session's id).
      If you are not sure a folder is yours, put it under "pending your `!`", never in the group you delete yourself.
   2. Split them:
      - **No `.git`**: delete them yourself with a literal path (`rm -rf {{DEV}}/_scratch/<topic>`), no question.
      - **With `.git`** (clones): never delete, only propose. First warn if the clone is dirty or unpushed:
        `git -C <path> status --short` and `git -C <path> log @{u}..` (no upstream = "unpushed branch").
        A clone whose PR is still open goes under "wait for the merge", not under deletable.
   3. Print ONE copyable block for the deletable clones, literal paths only (no variables, no `$(...)`, no globs):
      ```
      ! rm -rf {{DEV}}/_scratch/<topic>
      ```
   4. Add one line to the receipt: `Cleanup: deleted <paths> · pending your ! <paths> · none`. If there is nothing, only `Cleanup: none`.
