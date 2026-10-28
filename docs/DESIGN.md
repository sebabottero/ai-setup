# Design decisions

Five choices that shape ai-setup, and what each one costs.

## 1. One guard for every tool
**Decision:** a single `core/guard/guard.py` decides allow / ask / deny. Each adapter only translates its tool's hook format into that one JSON shape.

- **Why:** the rules cannot drift between Claude Code and OpenCode. A test written once covers both.
- **Cost:** the guard is the lowest common denominator. Tool-specific features (Claude's OS sandbox) live in the adapter, not in the shared logic.

## 2. A seatbelt, not a wall
**Decision:** the guard reads shell text with regexes and says so. The gaps it cannot see (base64, commands built inside a script) are listed in `tests/test_guard.py` (`KnownGaps`) as expected failures.

- **Why:** an honest limit beats a claim of safety. The real wall is the OS sandbox Claude gets from the same `policy.json`.
- **Cost:** in OpenCode there is no OS wall, only rules and the guard. The README table says so.

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
