#!/usr/bin/env python3
"""Render a gate file (criteria.md or plan.md) into its sibling .html, deterministically and with no agent step.

    python3 -I render_gate.py <dir>/criteria.md   -> <dir>/criteria.html   (prints the absolute path)
    python3 -I render_gate.py --check <dir>/criteria.md|.html  -> exit 0 when the .html is fresh, 1 when stale or missing, 2 on bad use
    python3 -I render_gate.py --prefs             -> gate_view=<md|html> and lang=<code> from the composed policy
    python3 -I render_gate.py --sha <file.md>     -> the sha256 of the .md bytes, for the agent-written page's `source-sha256` meta
    python3 -I render_gate.py --lint <dir>/criteria.html|plan.html  -> exit 0 silent when the agent-written page is sound, 1 with one
        `lint: ...` line per failure on stderr, 2 on bad use. Read-only. Checks: no external URL, an inline <svg>, every `C#` / `Paso #`
        in the visible text exists in the sibling criteria.md / plan.md, source-sha256 matches the .md; a criteria.html also needs
        .goal, .scope, a card (data-ref="C#") per criterion, .keep with non-empty data-keep irreversible / risks / deviations parts,
        and svg.slices when the .md has `## Slices`; a plan.html also needs .goal, svg.flow with one <g data-step="N"> per numbered step
        under `## Steps` (a `Paso N` text node plus a check text), .map with non-empty data-map touched / untouched / removed parts, .keep as
        above, .matrix when the .md has a "Criteria map" heading and .before-after when a heading matches before.*after. A plan.md with no
        numbered steps fails. The 1:1 page of this script fails --lint by design (criteria.html and plan.html): it is the fallback.
    python3 -I render_gate.py --mark-stale <dir>/criteria.html|plan.html  -> insert a visible `<div class="stale">` "outdated, see .md" banner
        (inline style, no url()) right after <body> of a page that is out of date, and nothing else: the rest stays byte for byte, a second
        run changes nothing (exit 0), exit 1 when the page is fresh, 2 on bad use or when the page has no <body>. --check still exits 1.

The .md stays the source of truth: the page carries `<meta name="source-sha256">` with the hash of the .md bytes, and
every numbered line under a "criteria" heading is copied verbatim. A `## Slices` section also becomes a dependency SVG.
Stdlib only; the output has no external URL (no http, <link>, src= or @import)."""
import hashlib, html, json, os, re, sys
from html.parser import HTMLParser

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


def stale(path):
    """Why the .html of a gate file is out of date (one line), or None when its source-sha256 matches the .md bytes."""
    base = os.path.abspath(path)
    stem = base[:-5] if base.endswith(".html") else base[:-3]
    md, page = stem + ".md", stem + ".html"
    if not os.path.isfile(md):
        return f"{md} is missing"
    if not os.path.isfile(page):
        return f"{page} is missing"
    try:
        with open(md, "rb") as f:
            want = hashlib.sha256(f.read()).hexdigest()
        with open(page, encoding="utf-8") as f:
            found = re.search(r'<meta\s+name="source-sha256"\s+content="([0-9a-f]*)"', f.read())
    except (OSError, UnicodeDecodeError) as err:
        return f"cannot read {md} or {page}: {str(err).splitlines()[0]}"
    if not found:
        return f"{page} has no source-sha256 meta"
    return None if found.group(1) == want else f"{page} source-sha256 differs from {md}"


EXTERNAL = re.compile(  # any scheme://, https:, a protocol-relative //, url() that is not a #fragment, src=, data=, <link>, <object>, <embed>, <iframe>, @import, http-equiv
    r"[a-z][a-z0-9+.-]*://[^\s\"'<>)]*|https?:[^\s\"'<>)]*|[=(]\s*[\"']?\s*//[^\s\"'<>)]*|\burl\(\s*(?![\"']?\s*#)[^)]*\)?"
    r"|<(?:link|object|embed|iframe)\b|\b(?:src|data)\s*=|@import\b|http-equiv", re.I)
HIDDEN = re.compile(r"<(style|script)\b.*?</\1\s*>|<!--.*?-->|<[^>]*>", re.S | re.I)  # what is not visible text: blocks, comments, tags with attributes
VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
KEEP_PARTS = ("irreversible", "risks", "deviations")
MAP_PARTS = ("touched", "untouched", "removed")


def steps_of(md):
    """The numbers of the top-level numbered lines under the `## Steps` heading (a heading whose text contains "step" or "paso").
    Bold lines do not end it and indented (nested) numbers do not count; a deeper sub-heading stays inside,
    a heading of the same or higher level ends it."""
    found, inside, level = [], False, 0
    for line in md.splitlines():
        head = HEADING.match(line)
        if head and inside and len(head.group(1)) > level:
            continue
        if head:
            text = head.group(2).lower()
            inside = "step" in text or "paso" in text
            level = len(head.group(1))
        elif inside and NUMBERED.match(line) and not line[:1].isspace():
            found.append(int(re.match(r"\d+", line).group(0)))
    return found


def numbered_under(md, words):
    """The numbers of the numbered lines under a heading that has one of `words` in it."""
    found, inside = set(), False
    for line in md.splitlines():
        head = HEADING.match(line)
        if head or BOLD_LINE.match(line):  # same section markers as blocks(): a heading or a bold line
            inside = any(w in (head.group(2) if head else line).lower() for w in words)
        elif inside and NUMBERED.match(line):
            found.add(int(re.match(r"\s*(\d+)", line).group(1)))
    return found


class Structure(HTMLParser):
    """What the page has: class names, svg.slices, svg.flow, card refs, the text of each data-keep / data-map part and the text nodes of
    each <g data-step> inside an svg.flow."""
    def __init__(self):
        super().__init__()
        self.classes, self.cards, self.keep, self.maps, self.steps = set(), set(), {}, {}, {}
        self.stack, self.slices, self.flow = [], False, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        names = (a.get("class") or "").split()
        self.classes.update(names)
        if tag == "svg" and "slices" in names:
            self.slices = True
        if tag == "svg" and "flow" in names:
            self.flow = True
        if "card" in names and a.get("data-ref"):
            self.cards.add(a["data-ref"])
        key, part, step = a.get("data-keep"), a.get("data-map"), a.get("data-step")
        if key is not None:
            self.keep.setdefault(key, "")
        if part is not None:
            self.maps.setdefault(part, "")
        in_flow = any(e[3] for e in self.stack) or (tag == "svg" and "flow" in names)
        if step is not None and in_flow and tag == "g":
            self.steps.setdefault(step, [])
        else:
            step = None
        if tag not in VOID:
            self.stack.append((tag, key, part, tag == "svg" and "flow" in names, step))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        for _, key, part, _, step in self.stack:
            if key is not None:
                self.keep[key] += data
            if part is not None:
                self.maps[part] += data
            if step is not None:
                self.steps[step].append(data)


def parts_missing(found, attr, wanted, fails):
    """One line per wanted data-<attr> part that is missing or has no text."""
    have = found.keep if attr == "keep" else found.maps
    for part in wanted:
        if part not in have:
            fails.append(f"lint: no data-{attr}={part}")
        elif not have[part].strip():
            fails.append(f"lint: data-{attr}={part} is empty")


def plan_structure(found, md, fails):
    """The checks of a plan.html against its plan.md: goal, svg.flow with one data-step group per step, map, keep, matrix, before-after."""
    if "goal" not in found.classes:
        fails.append("lint: no .goal")
    steps = steps_of(md)
    if not steps:
        fails.append("lint: plan.md has no numbered steps")
    if not found.flow:
        fails.append("lint: no svg.flow")
    for n in steps:
        nodes = found.steps.get(str(n))
        if nodes is None:
            fails.append(f"lint: no data-step={n} in svg.flow")
            continue
        texts = [t.strip() for t in nodes if t.strip()]
        label = f"Paso {n}"
        if label not in texts:
            fails.append(f"lint: data-step={n} has no single `{label}` text")
        elif all(t == label for t in texts):  # nothing but the label: no check
            fails.append(f"lint: data-step={n} has no check text")
    if "map" not in found.classes:
        fails.append("lint: no .map")
    parts_missing(found, "map", MAP_PARTS, fails)
    if "keep" not in found.classes:
        fails.append("lint: no .keep")
    parts_missing(found, "keep", KEEP_PARTS, fails)
    headings = [m.group(2).lower() for m in map(HEADING.match, md.splitlines()) if m]
    if any("criteria map" in h for h in headings) and "matrix" not in found.classes:
        fails.append("lint: no .matrix (the .md has a Criteria map)")
    if any(re.search(r"before.*after", h) for h in headings) and "before-after" not in found.classes:
        fails.append("lint: no .before-after (the .md has a before/after heading)")


def lint(path):
    """One `lint: ...` line per failure of the agent-written page at `path` (empty list = sound). Read-only."""
    base = os.path.abspath(path)
    folder, name = os.path.split(base)
    stem = base[:-5]
    try:
        with open(base, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as err:
        return [f"lint: cannot read {name}: {str(err).splitlines()[0]}"]
    fails = []
    for found in dict.fromkeys(m.group(0) for m in EXTERNAL.finditer(text)):
        fails.append(f"lint: external URL: {found}")
    if "<svg" not in re.sub(r"<!--.*?-->", "", text, flags=re.S):
        fails.append("lint: no inline <svg>")
    visible = html.unescape(HIDDEN.sub(" ", text))
    sources = {}  # sibling .md name -> its text, or None when missing

    def source(md_name):
        if md_name not in sources:
            try:
                with open(os.path.join(folder, md_name), encoding="utf-8-sig") as f:
                    sources[md_name] = f.read()
            except (OSError, UnicodeDecodeError):
                sources[md_name] = None
                fails.append(f"lint: {md_name} is missing or unreadable")
        return sources[md_name]

    for word, md_name, words, noun in (("C", "criteria.md", ("criteria",), "a criterion"), ("Paso ", "plan.md", ("step", "paso"), "a step")):
        for n in sorted({int(m) for m in re.findall(rf"\b{word}(\d+)\b", visible)}):
            md = source(md_name)
            known = set(steps_of(md)) if md is not None and word == "Paso " else numbered_under(md, words) if md is not None else set()
            if md is not None and n not in known:
                fails.append(f"lint: {word}{n} is not {noun} in {md_name}")
    mine = source(name[:-5] + ".md")
    why = stale(base)
    if why and mine is not None:
        fails.append("lint: " + why.replace(folder + os.sep, ""))
    if name == "criteria.html" and mine is not None:
        found = Structure()
        found.feed(text)
        for cls in ("goal", "scope", "keep"):
            if cls not in found.classes:
                fails.append(f"lint: no .{cls}")
        for n in sorted(numbered_under(mine, ("criteria",))):
            if f"C{n}" not in found.cards:
                fails.append(f"lint: no card for C{n}")
        parts_missing(found, "keep", KEEP_PARTS, fails)
        if slices_of(mine.splitlines()) and not found.slices:
            fails.append("lint: no svg.slices (the .md has ## Slices)")
    if name == "plan.html" and mine is not None:
        found = Structure()
        found.feed(text)
        plan_structure(found, mine, fails)
    return fails


BANNER_STYLE = "position:sticky;top:0;z-index:9;margin:0;padding:10px 16px;background:#b3261e;color:#fff;font:600 15px system-ui,sans-serif;text-align:center"
SKIPPED = re.compile(rb"<!--.*?-->|<(script|style)\b.*?</\1\s*>", re.S | re.I)  # where a tag is not a tag
BODY_TAG = re.compile(rb"<body(?:\s(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)?>", re.I)
STALE_DIV = re.compile(rb"<div\s+class=\"stale\"", re.I)


def outside(pattern, raw):
    """The first match of `pattern` in `raw` that is not inside a comment, <script> or <style>, or None."""
    spans = [m.span() for m in SKIPPED.finditer(raw)]
    return next((m for m in pattern.finditer(raw) if not any(a <= m.start() < b for a, b in spans)), None)


def mark_stale(path):
    """(exit code, message). Inserts the banner right after <body> of a stale page, byte-exact; nothing else changes."""
    why = stale(path)
    if why is None:
        return 1, "render_gate: page is fresh, nothing to mark"
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as err:
        return 2, f"render_gate: cannot read {path}: {err}"
    if outside(STALE_DIV, raw):
        return 0, os.path.abspath(path)
    body = outside(BODY_TAG, raw)
    if not body:
        return 2, f"render_gate: {path} has no <body>, nothing marked"
    md = os.path.basename(path)[:-5] + ".md"
    banner = f'<div class="stale" style="{BANNER_STYLE}">Outdated, see .md: {md} changed after this page was written.</div>'.encode()
    try:
        with open(path, "wb") as f:
            f.write(raw[:body.end()] + banner + raw[body.end():])
    except OSError as err:
        return 2, f"render_gate: cannot write {path}: {err}"
    return 0, os.path.abspath(path)


def prefs():
    """(preferences, warning or None). A gate_view that is not md or html is read as md and the warning says so."""
    sys.path.insert(0, HERE)  # under `python3 -I` the script folder is not on sys.path
    import guard, layers
    given = os.environ.get("AI_SETUP_POLICY")
    if given:
        with open(given) as f:
            policy = json.load(f)
    else:
        policy = guard.load()
    warning = f"render_gate: gate_view {policy['gate_view']!r} is not md or html, using md" if layers.unknown_gate_view(policy) else None
    return layers.preferences(policy), warning


def main(argv):
    if argv == ["--prefs"]:
        values, warning = prefs()
        for key, value in values.items():
            print(f"{key}={value}")
        if warning:
            print(warning, file=sys.stderr)
        return 0
    if argv[:1] == ["--sha"] and len(argv) == 2:
        try:
            with open(argv[1], "rb") as f:
                print(hashlib.sha256(f.read()).hexdigest())
        except OSError as err:
            print(f"render_gate: cannot read {argv[1]}: {err}", file=sys.stderr)
            return 2
        return 0
    if argv[:1] == ["--lint"] and len(argv) == 2 and os.path.basename(argv[1]) in KINDS.values():
        fails = lint(argv[1])
        for line in fails:
            print(line, file=sys.stderr)
        return 1 if fails else 0
    if argv[:1] == ["--mark-stale"]:
        if len(argv) != 2 or os.path.basename(argv[1]) not in KINDS.values():
            print(__doc__.split("\n\n")[0], file=sys.stderr)
            return 2
        code, message = mark_stale(argv[1])
        print(message, file=sys.stdout if code == 0 else sys.stderr)
        return code
    check = argv[:1] == ["--check"]
    if check:
        argv = argv[1:]
    if len(argv) != 1 or argv[0].startswith("-"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    name = os.path.basename(argv[0])
    if name.endswith(".html") and check:
        name = name[:-5] + ".md"
    if name not in KINDS:
        print(f"render_gate: only {' and '.join(KINDS)} can be {'checked' if check else 'rendered'}, not '{os.path.basename(argv[0])}'", file=sys.stderr)
        return 2
    if check:
        why = stale(argv[0])
        if why:
            print(f"render_gate: stale: {why}", file=sys.stderr)
        return 1 if why else 0
    try:
        print(render_file(argv[0]))
    except (OSError, UnicodeDecodeError) as err:
        print(f"render_gate: cannot render {argv[0]}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
