# Recommended skills

Third-party skills that pair well with `ticket-flow`. They are linked, not copied: no third-party code lives in this repo, so
their licenses and updates stay with their authors. Run the command from the root of your `ai-setup` clone.

| Skill | What it adds | Install |
|---|---|---|
| `tdd` | Red-green-refactor loop for features | `./add-skill.sh https://github.com/mattpocock/skills skills/engineering/tdd` |
| `systematic-debugging` | Reproduce, isolate and fix a bug with evidence | `./add-skill.sh https://github.com/obra/superpowers skills/systematic-debugging` |

`add-skill.sh` copies the skill into `<layer>/skills/` (default `core`), records the URL and commit in that layer's `sources.json`
and installs it in every tool. It does not run anything it downloads: read the `SKILL.md` and any script before relying on it.
Use `--layer <name>` to keep them in your own layer, and `./add-skill.sh --update <name>` to refresh one. More in the
[Reference](REFERENCE.md).
