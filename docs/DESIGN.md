# Design decisions

Six choices that shape ai-setup, and what each one costs.

## 1. One guard for every tool
**Decision:** a single `core/guard/guard.py` decides allow / ask / deny. Each adapter only translates its tool's hook format into that one JSON shape.

- **Why:** the rules cannot drift between Claude Code and OpenCode. A test written once covers both.
- **Cost:** the guard is the lowest common denominator. Tool-specific features (Claude's OS sandbox) live in the adapter, not in the shared logic.

## 2. A seatbelt, not a wall
**Decision:** the guard reads shell text with regexes and says so. The gaps it cannot see (base64, commands built inside a script) are listed in `tests/test_guard.py` (`KnownGaps`) as expected failures.

- **Why:** an honest limit beats a claim of safety. The real wall is the OS sandbox Claude gets from the same `policy.json`.
- **Cost:** in OpenCode there is no OS wall by default, only rules and the guard; `install.py --opencode-sandbox` opts in to an `srt` wall built from the same policy (settings still to verify against srt). The README table says so.

## 3. One writer per ticket
**Decision:** `flow-ticket` plans on the strong model. A single `sub-builder` writes, inside its own git worktree and an allowlist. Review, tests and checks are read-only and run in parallel.

- **Why:** no two agents edit the same files, and the agent that wrote the code never grades it.
- **Cost:** writing is sequential. Claude Code cannot limit paths per subagent, so the allowlist is enforced by the prompt there and by config in OpenCode.

## 4. Layers only add
**Decision:** `core/` is generic and always installed. Your language, tone and company tools go in extra layers, which can live in a private repo (`--layers-dir`). A layer can add rules and never remove one.

- **Why:** the public repo stays free of anything personal, and nobody can weaken `core/` by installing a layer.
- **Cost:** you cannot loosen a core rule from a layer. The one exception is `allow_*` in a layer's `policy.json`, and editing it asks for OK.

## 5. Merge, back up, check before writing
**Decision:** the installer merges into `settings.json` and `opencode.json` instead of replacing them. It copies whatever it replaces to `~/.ai-setup-backups/<date>/`. It checks the composed policy (nothing both allowed and asked) before touching anything.

- **Why:** your hand-written rules survive, and a bad layer stops the install with the offending rule.
- **Cost:** choosing fewer layers removes nothing by itself. You uninstall a layer explicitly with `--uninstall`.

## 6. Protected paths: native ask outside ticket worktrees, scoped ask inside them
**Decision (variant E):** a protected path in the main checkout (or `~/.config/opencode/...`) asks on every edit through Claude Code's own `Edit(<path>)` ask rules, exactly as before. Inside a ticket worktree (`<dev root>/worktrees/<repo>/<ticket>/`) a PreToolUse hook on `Edit|Write|MultiEdit|NotebookEdit` is the wall: the paths the ticket's Gate 1 named (exact, in a scope file written by `core/guard/scope.py add`) ask once, every other protected path asks every time. `policy.json` is unchanged and no rule for any other path was loosened.

- **History:** first decided as option B (no scoped approvals, PR #36), because in Claude Code 2.1.317 a hook `allow` does not override a settings `ask` rule (read from the binary) and a hook as the only wall looked like lost defense in depth. Changed to E after weighing criterion 12 against ask fatigue: the native rules are absolute paths of the main checkout, so they never covered a worktree copy of the same file; the hook therefore adds a wall inside worktrees, it does not replace one, and the native rules that exist are kept untouched.
- **Why E and not removing the native rules everywhere (option A):** the hook can only ask once if no native `ask` rule matches the path. Dropping the rules in the main checkout too would make every protected file depend on one hook. E narrows the rules only for paths under `<dev root>/worktrees`, where none matched before.
- **Trade-off:** inside worktrees the wall is the hook alone. If it errors, it answers `ask`. **Residual fail-open case:** if the hook does not run at all (uninstalled, settings.json overwritten, interpreter crash, hook timeout) a protected file in a worktree is editable like any file there (auto mode and `work_dirs` allow edits). Mitigations: an install-time check (the hook must ask for a protected path of a throwaway worktree) and a SessionStart warning when the hook is not registered; the sandbox `denyWrite` still blocks Bash writes to the main checkout's protected paths. A second residual: the scope only covers worktrees under `<dev root>/worktrees`; the scope file is trusted state in `~/.ai-setup/scopes` (not writable from the sandbox; `scope.py add` and edits of that folder ask).
- **Verified vs inferred:** verified in the 2.1.317 binary strings: hook `allow` never beats ask or deny rules, PostToolUse accepts an `Edit|Write` matcher, the payload carries `tool_use_id`. Inferred: a hook `ask` raises a prompt when no native rule exists (the Bash guard already relies on it), `tool_input.file_path` for Edit / Write. Manual 2-minute probe: `handoffs/harness-gaps/s7-findings-v2.md`.
- **How to measure it:** `python3 adapters/claude/usage_report.py N` gives asks per day and approval rate from `guard.log` and `actions.log`; compare the weeks before and after this change. The scoped hook writes one `guard.log` line (`edit`, decision, `scoped-edit`) for every protected path it judges, so its asks are in the counts; they have no `actions.log` outcome line, so they show as unresolved in the approval rate. `scope.py add` and `clear` are `scope-write` asks in `actions.log`.
- **Cost:** one prompt per scoped path per ticket instead of one per edit; every other protected path still asks every time; one more hook and one more state folder to trust.
