---
name: visual-guides
description: Write short, visual, step-by-step guides, manuals and cheatsheets for the user ("how to use X"), and produce self-contained HTML pages (guide, criteria, plan, repo-doc templates) with no external URLs. Use when asked for "cheatsheet", "manual", "guide", "how do I use X", "step by step", "make it visual", "as HTML", "guía", "cómo uso X", "paso a paso", "explícame cómo se usa", or when documenting a tool, skill or workflow for the user's own use. Not for PRs or tickets.
---

# Visual guides

## Language
Write in the `lang` preference, never a hard-coded language. Read it first:

```
python3 -I {{AI_SETUP}}/core/guard/render_gate.py --prefs
```
It prints `gate_view=<md|html>` and `lang=<code>` (defaults `md` and `en`; a layer's `policy.json` can set them). Commands and code stay as they are. The `repo-doc` template is always English.

## Guide format (always this order)
1. **Title + one line:** what it is for and when to use it.
2. **Step by step:** numbered, 5 steps at most, one action (one command) per step.
3. **Real example:** a copy-paste block with the output the reader should see.
4. **If it fails:** table `error -> fix`, 5 rows at most.
5. **Last line:** the first action the reader can do in under 2 minutes.

## Rules
- One screen. If it does not fit, split it into two guides.
- Show, do not describe: tables, flows (`A -> B -> C`), code blocks. A paragraph is the last resort.
- Most common case first; edge cases in a short "also" table.
- No theory or history unless asked. Use real paths, repos and commands when known.
- SVG only when it adds something (a branching flow, dependencies, an architecture). Never for a linear list.
- Format: `.md` by default. When the user asks for "visual" or "HTML", write one self-contained `.html` from the `guide` template.

## Templates
All are in `{{AI_SETUP}}/core/skills/visual-guides/templates/`: one `.html` file, inline CSS (light and dark), no external URL, no `<link>`, no `src=`, no `@import`. Placeholders: `{{TITLE}}`, `{{BODY}}`, `{{SHA}}`.

| Template | Use it for | Who writes it |
|---|---|---|
| `guide` | a how-to for the user: steps as cards, example, "if it fails", next action | you, filling `{{TITLE}}` and `{{BODY}}` |
| `criteria` | the HTML view of a `criteria.md` | only `render_gate.py` |
| `plan` | the HTML view of a `plan.md` | only `render_gate.py` |
| `repo-doc` | human docs of a repo that asks for HTML (see "Human docs in a repo"), always English | you, filling `{{TITLE}}` and `{{BODY}}` |

Body of a `guide`: `<p class="lead">` for the one line, then one `<div class="step"><h3><span class="n">1</span>Title</h3>...</div>` per step, `<pre><code>` for the example, a `<table>` for "if it fails", and `<p class="next">` last. Escape every `<`, `>` and `&` you copy from the user's text.

## Human docs in a repo
A repo opts in with one line in its `AGENTS.md` or `CONTRIBUTING.md`: `Human docs: html` (any case), a plain line, optionally as a `-` list item. The docs writer checks it from the repo root:

```sh
cat AGENTS.md CONTRIBUTING.md 2>/dev/null | grep -iE '^[[:space:]]*([-*][[:space:]]+)?human docs:[[:space:]]*html([^[:alnum:]_-]|$)'
```
A printed line means declared (exit 0; 1 means not), even when only one of the two files exists. A match means the human docs the ticket adds or changes (guides and how-tos for people; not README, REFERENCE or agent rules) are written as one self-contained `.html` from the `repo-doc` template, always in English whatever `lang` says, next to the neighbouring docs. The declaration overrides only the language and the format of those docs; every other rule of the repo's docs still applies. No match: write docs as the repo's own rules say.

## Gate pages (`criteria`, `plan`)
Never write these by hand. The `.md` is the source of truth and agents keep reading it:

```
python3 -I {{AI_SETUP}}/core/guard/render_gate.py <dir>/criteria.md
```
It writes the sibling `.html`, copies every criterion line verbatim, stores the hash of the `.md` in `<meta name="source-sha256">`, draws the slice dependency SVG when the `.md` has `## Slices`, and prints the path.

## Before handing it over
Read only the title and step headings: can the reader do the task? If not, cut and reorder.
