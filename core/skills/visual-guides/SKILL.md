---
name: visual-guides
description: Write short, visual, step-by-step guides, manuals and cheatsheets for the user ("how to use X"), and produce self-contained HTML pages (guide, criteria, plan, repo-doc templates) with no external URLs. Use when asked for "cheatsheet", "manual", "guide", "how do I use X", "step by step", "make it visual", "as HTML", "guía", "cómo uso X", "paso a paso", "explícame cómo se usa", "design", "mockup", "table layout", "diseño", "tabla", or when documenting a tool, skill or workflow for the user's own use. Not for PRs or tickets.
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

## Design rule
Applies to ANY design (tables, Sheets blocks, HTML pages, mockups), not only guides. Every design must be very visual, simple and easy to understand, practical, and include a practical example (a real number or case, never an abstract description). Show it instead of describing it.

## Templates
All are in `{{AI_SETUP}}/core/skills/visual-guides/templates/`: one `.html` file, inline CSS (light and dark), no external URL, no `<link>`, no `src=`, no `@import`. Placeholders: `{{TITLE}}`, `{{BODY}}`, `{{SHA}}`.

| Template | Use it for | Who writes it |
|---|---|---|
| `guide` | a how-to for the user: steps as cards, example, "if it fails", next action | you, filling `{{TITLE}}` and `{{BODY}}` |
| `criteria` | the HTML view of a `criteria.md` | you, filling `{{BODY}}` with the skeleton under "Gate pages" (`render_gate.py` fills the same template 1:1 as fallback) |
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
The `.md` is the source of truth and agents keep reading it; the page is a one-screen visual summary of it. `plan` pages are still written only by `render_gate.py`.

**`criteria.html`, written by you** from the `criteria` template: get the hash with `python3 -I {{AI_SETUP}}/core/guard/render_gate.py --sha <dir>/criteria.md` (fills `{{SHA}}`), keep the template's `<head>` and CSS, and fill `{{BODY}}`:
```
<p class="goal">goal in one line</p>
<section class="scope"><div class="in">in scope</div><div class="out">out of scope</div></section>
<section class="cards"><article class="card" data-ref="C1"><b class="ref">C1</b>
  <p class="given">…</p><p class="when">…</p><p class="then">…</p></article> …one per criterion</section>
<section class="keep">
  <div data-keep="irreversible">push, delete, tracker/Drive/sheet writes, migrations, or none</div>
  <div data-keep="risks">open questions and risks, or none</div>
  <div data-keep="deviations">deviations from the handoff, or none</div></section>
<svg class="slices" …>
```
- The `keep` block is always present and its content is never dropped by the summary: copy every irreversible action, open question, risk and deviation from the `.md`; write `none` when there is nothing, never leave a part empty.
- Number cards `C1`… exactly as in the `.md`; never invent a `C#` or `Paso #` that the `.md` does not have.
- SVG: inline, no `xmlns`, colours with `currentColor` or the template's variables. With `## Slices` in the `.md`, copy the slice SVG (`svg.slices`) that `render_gate.py <criteria.md>` draws; otherwise draw a small criteria-flow SVG. Escape every `<`, `>` and `&` you copy.
- No external URL (no `http`, `<link>`, `src=`, `@import`).

**Check it** with `render_gate.py --lint <dir>/criteria.html`: exit 0 and silent is a pass; exit 1 prints one `lint: ...` line per failure (external URL, no inline `<svg>`, a `C#` or `Paso #` missing from the sibling `.md`, `source-sha256` differing, no goal / scope / card / `keep` part / `svg.slices`). Fix and lint once more. Failing twice: write the 1:1 page instead with `python3 -I {{AI_SETUP}}/core/guard/render_gate.py <dir>/criteria.md` (it copies every criterion line verbatim, stores the hash in `<meta name="source-sha256">`, draws the slice SVG, prints the path) and say in the gate message that the visual summary failed and why. A 1:1 page fails `--lint` by design and is never reused as a visual page.

Gates check the page is fresh with `render_gate.py --check <file>` (exit 1 when stale or missing) and re-render before showing it.

## Before handing it over
Read only the title and step headings: can the reader do the task? If not, cut and reorder.
