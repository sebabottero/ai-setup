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

## 6. Protected paths: native ask everywhere it matched, scoped ask inside ticket worktrees
**Decision (variant E):** every protected path keeps its native `Edit(<path>)` ask rule exactly as before: they are absolute paths of the main checkout and ask on every edit. Inside a ticket worktree (`<dev root>/worktrees/<repo>/<ticket>/`) a PreToolUse hook on `Edit|Write|MultiEdit|NotebookEdit` is the wall: the paths the ticket's Gate 1 named (exact, in a scope file the owner writes with `core/guard/scope.py add`) ask once, every other protected path asks every time. `policy.json` is unchanged and no rule for any other path was loosened.

- **History:** first decided as option B (no scoped approvals, PR #36), because in Claude Code 2.1.317 a hook `allow` does not override a settings `ask` rule (read from the binary) and a hook as the only wall looked like lost defense in depth. Changed to E after weighing criterion 12 against ask fatigue. A first version of E also removed the native rules for paths under `<dev root>/worktrees`; review showed that does nothing useful (the rules never matched a worktree copy) and drops every native ask when the installer runs from a worktree, so it was deleted: all native rules are kept, the hook only adds a wall.
- **Why a hook and not a native rule inside worktrees:** a native `ask` rule would hide a hook `allow`, so ask-once is impossible with one; and none matches a worktree path anyway.
- **Trade-off:** inside worktrees the wall is the hook alone. If it errors, it answers `ask`. **Residual fail-open case:** if the hook does not run at all (uninstalled, settings.json overwritten, interpreter crash, hook timeout) a protected file in a worktree is editable like any file there (auto mode and `work_dirs` allow edits); before this change those files were not protected there either. Mitigations: an install-time check (the hook must ask for a protected path of a throwaway worktree), a loud warning when installing from a worktree, a SessionStart warning when the hook is not registered, and the sandbox `denyWrite`, which still blocks Bash writes to the main checkout's protected paths.
- **The scope is owner-written state:** the scope file lives in `~/.ai-setup/scopes`, outside the sandbox's write list. It is created by a `! ` line the owner runs, not by the agent; `sandbox.excludedCommands` deliberately has no `scope.py` entry (matching against compound lines is unverified, and an entry could let the agent write its own scope). The guard asks for every use of `scope.py` but one plain `show`, and the hook asks for any edit of the scopes, pending and sessions folders under any case. A scope is bound to the worktree's `.git` file (a recreated worktree inherits nothing), expires after 72 h, and its grants after 12 h; `ticket-flow` has the owner run `scope.py clear` when the worktree is deleted.
- **More limits:** hardlinks to a protected file are judged by their own name; the scope only covers `<dev root>/worktrees` (workspace folders elsewhere get no hook ask, as before); a grant also follows an ask that auto mode let through with no human; criterion 12's example `tests/test_guard.py` is not in core `protected_paths`, so it holds only for files that are protected; Unicode-equivalent spellings are not normalised. Case variants of folder names (macOS) were a bypass in the first version and are fixed: all folder comparisons ignore case.
- **Verified vs inferred:** verified live (headless `claude -p` 2.1.317, 2026-11-23; the interactive prompt UI was not observed): a hook `ask` is honoured with no native rule, a hook `allow` lets the Write through in default mode. Verified in the binary strings only: a hook `allow` never beats an ask or deny rule, PostToolUse accepts an `Edit|Write` matcher, the payload carries `tool_use_id`. Inferred: `tool_input.file_path` for Edit / Write, behaviour of `ask` in auto mode. Details: `handoffs/harness-gaps/s7-findings-v2.md`.
- **How to measure it:** `python3 adapters/claude/usage_report.py N` gives asks per day and approval rate from `guard.log` and `actions.log`; compare the weeks before and after this change. The scoped hook writes one `guard.log` line (`edit`, decision, `scoped-edit`) for every protected path it judges, so its asks are in the counts and the "asks / guard decisions" baseline shifts; they have no `actions.log` outcome line, so they show as unresolved in the approval rate. `scope.py` uses are `scope-write` asks in `actions.log`.
- **Cost:** one prompt per scoped path per ticket (per 12 h) instead of one per edit, plus one command the owner runs per ticket; every other protected path still asks every time; one more hook and one more state folder to trust.
