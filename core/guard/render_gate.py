#!/usr/bin/env python3
"""Render a gate file (criteria.md or plan.md) into its sibling .html, deterministically and with no agent step.

    python3 -I render_gate.py <dir>/criteria.md   -> <dir>/criteria.html   (prints the absolute path)
    python3 -I render_gate.py --prefs             -> gate_view=<md|html> and lang=<code> from the composed policy

The .md stays the source of truth: the page carries `<meta name="source-sha256">` with the hash of the .md bytes, and
every numbered line under a "criteria" heading is copied verbatim. A `## Slices` section also becomes a dependency SVG.
Stdlib only; the output has no external URL (no http, <link>, src= or @import)."""
import hashlib, html, json, os, re, sys

HERE = os.path.dirname(os.path.realpath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "skills", "visual-guides", "templates")
KINDS = {"criteria.md": "criteria.html", "plan.md": "plan.html"}  # file name -> template


def esc(text):
    return html.escape(text, quote=True)


def inline(text):
    """Escape, then `code` and **bold**. Code spans are cut out first so nothing inside them is touched."""
    out = []
    for i, part in enumerate(re.split(r"`([^`]*)`", text)):
        if i % 2:
            out.append(f"<code>{esc(part)}</code>")
        else:
            out.append(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(part)))
    return "".join(out)


HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+")
BOLD_LINE = re.compile(r"^\s*\*\*.+")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_rule(line):
    return bool(re.fullmatch(r"\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*", line))


def slices_of(lines):
    """[(id, label, [parent ids])] from the `- ID: field · field · depends on A and B` lines of the ## Slices section."""
    found, inside = [], False
    for line in lines:
        head = HEADING.match(line)
        if head:
            inside = head.group(2).strip().lower() == "slices"
            continue
        item = BULLET.match(line) if inside else None
        node = re.match(r"(\w+):\s*(.*)$", item.group(1)) if item else None
        if node:
            found.append((node.group(1), [f.strip() for f in node.group(2).split(" · ")]))
    ids = [i for i, _ in found]
    nodes = []
    for ident, fields in found:
        deps = [f for f in fields if "depends on" in f.lower()]
        parents = [w for f in deps for w in re.findall(r"\w+", f.split("depends on", 1)[-1]) if w in ids and w != ident]
        label = next((f for f in fields if f not in deps), "")
        nodes.append((ident, label, list(dict.fromkeys(parents))))
    return nodes


def slices_svg(nodes):
    """Inline SVG: one box per slice, a column per dependency depth, an arrow from each dependency to its dependent."""
    parents = {i: p for i, _, p in nodes}
    depth = {}

    def of(ident, seen=()):
        if ident not in depth:
            ups = [p for p in parents.get(ident, []) if p not in seen and p != ident]
            depth[ident] = 1 + max((of(p, seen + (ident,)) for p in ups), default=-1)
        return depth[ident]

    for ident, _, _ in nodes:
        of(ident)
    w, h, gx, gy, pad = 170, 54, 60, 18, 12
    rows, pos = {}, {}
    for ident, _, _ in nodes:
        col = depth[ident]
        pos[ident] = (pad + col * (w + gx), pad + rows.get(col, 0) * (h + gy))
        rows[col] = rows.get(col, 0) + 1
    width = pad * 2 + (max(depth.values()) + 1) * w + max(depth.values()) * gx
    height = pad * 2 + max(rows.values()) * h + (max(rows.values()) - 1) * gy
    parts = [f'<svg class="slices" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="Slice dependencies">',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
             '<path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>']
    for ident, _, ups in nodes:
        for up in ups:
            (x1, y1), (x2, y2) = pos[up], pos[ident]
            sx, sy, ex, ey = x1 + w, y1 + h // 2, x2, y2 + h // 2
            mid = (sx + ex) // 2
            parts.append(f'<path class="arrow" d="M{sx} {sy} C{mid} {sy} {mid} {ey} {ex} {ey}" fill="none" stroke="currentColor" '
                         f'stroke-width="1.5" marker-end="url(#arrow)"/>')
    for ident, label, _ in nodes:
        x, y = pos[ident]
        short = label if len(label) <= 26 else label[:25] + "…"
        parts.append(f'<g class="slice"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8"/>'
                     f'<text x="{x + 10}" y="{y + 22}" class="id">{esc(ident)}</text>'
                     f'<text x="{x + 10}" y="{y + 40}" class="label">{esc(short)}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def blocks(lines):
    """The body HTML of the Markdown subset: headings, paragraphs, lists, fenced code, pipe tables, inline code and bold.
    Numbered lines under a heading or bold line that says "criteria" are copied whole and verbatim."""
    out, para, items, kind = [], [], [], None
    in_criteria = False
    i = 0

    def flush():
        nonlocal para, items, kind
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
        if items:
            if kind == "criteria":
                out.append('<ul class="criteria">' + "".join(f'<li class="criterion">{esc(t)}</li>' for t in items) + "</ul>")
            else:
                tag = "ol" if kind == "ol" else "ul"
                out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
        para, items, kind = [], [], None

    def add(new_kind, text):
        nonlocal kind
        if kind != new_kind:
            flush()
            kind = new_kind
        items.append(text)

    while i < len(lines):
        line = lines[i]
        head = HEADING.match(line)
        if line.strip().startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
        elif head:
            flush()
            level = len(head.group(1))
            in_criteria = "criteria" in head.group(2).lower()
            out.append(f"<h{level}>{inline(head.group(2))}</h{level}>")
        elif BOLD_LINE.match(line):
            flush()
            in_criteria = "criteria" in line.lower()
            para.append(line.strip())
        elif not line.strip():
            flush()
        elif in_criteria and NUMBERED.match(line):
            add("criteria", line.strip())
        elif NUMBERED.match(line):
            add("ol", NUMBERED.sub("", line, 1).strip())
        elif BULLET.match(line):
            add("ul", BULLET.match(line).group(1).strip())
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and is_rule(lines[i + 1]):
            flush()
            head_cells, rows = cells(line), []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            i -= 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head_cells) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")
        elif kind == "criteria" and line[0] in " \t":
            items[-1] += " " + line.strip()  # a wrapped criterion stays one item
        else:
            if items:
                flush()
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def render(text, template, sha):
    lines = text.splitlines()
    title = next((m.group(2) for m in map(HEADING.match, lines) if m and len(m.group(1)) == 1), "Gate")
    body = blocks(lines)
    nodes = slices_of(lines)
    if nodes:
        body += '\n<section class="slice-graph"><h2>Slice dependencies</h2>' + slices_svg(nodes) + "</section>"
    values = {"TITLE": esc(title), "BODY": body, "SHA": sha}
    return re.sub(r"\{\{(TITLE|BODY|SHA)\}\}", lambda m: values[m.group(1)], template)  # one pass: the body is never re-expanded


def render_file(path):
    name = os.path.basename(path)
    with open(path, "rb") as f:
        raw = f.read()
    with open(os.path.join(TEMPLATES, KINDS[name]), encoding="utf-8") as f:
        template = f.read()
    out = os.path.join(os.path.dirname(os.path.abspath(path)), name[:-3] + ".html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(raw.decode("utf-8-sig"), template, hashlib.sha256(raw).hexdigest()))
    return out


def prefs():
    sys.path.insert(0, HERE)  # under `python3 -I` the script folder is not on sys.path
    import guard, layers
    given = os.environ.get("AI_SETUP_POLICY")
    if given:
        with open(given) as f:
            return layers.preferences(json.load(f))
    return layers.preferences(guard.load())


def main(argv):
    if argv == ["--prefs"]:
        for key, value in prefs().items():
            print(f"{key}={value}")
        return 0
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    if os.path.basename(argv[0]) not in KINDS:
        print(f"render_gate: only {' and '.join(KINDS)} can be rendered, not '{os.path.basename(argv[0])}'", file=sys.stderr)
        return 2
    try:
        print(render_file(argv[0]))
    except (OSError, UnicodeDecodeError) as err:
        print(f"render_gate: cannot render {argv[0]}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
