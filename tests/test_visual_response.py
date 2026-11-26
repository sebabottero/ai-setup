"""Visual response: preferences (gate_view, lang), the visual-guides skill and render_gate.py. One test per criterion of
the ticket, named after it. Criterion 6: reviewers, testers and audit read criteria.md / plan.md, never a gate .html."""
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, unittest
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import layers

RENDER = os.path.join(ROOT, "core", "guard", "render_gate.py")
SKILL_DIR = os.path.join(ROOT, "core", "skills", "visual-guides")
TEMPLATES = os.path.join(SKILL_DIR, "templates")
NAMES = ("guide", "criteria", "plan", "repo-doc")
EXTERNAL = re.compile(r"https?:|<link\b|\bsrc\s*=|@import|xmlns", re.I)

CRITERIA = """# Criteria: sample
## Out of scope
- 1. not a criterion & <b>raw</b>
## Criteria
1. Given `a` & <b>b</b>, when it runs, then **x** holds.
2. Given another one, then it holds.
## Done
All pass.
## Slices
- PR1: criteria 1-2 · core
- PR2: criterion 3 · depends on PR1 · gates
- PR3: criterion 4 · depends on PR1 · docs
- PR4: other repo · depends on PR1 and PR2 · personal
"""
PLAN = """# Plan: sample
**(d) Success criteria (verbatim):**
1. Given X, when Y, then Z.
2. Given A, when B, then C.
**(e) Other:** n/a.
## Steps
1. do it
"""


def run(*args, env=None):
    return subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, env=env)


def slurp(path, binary=False):
    with open(path, "rb" if binary else "r", **({} if binary else {"encoding": "utf-8"})) as f:
        return f.read()


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


class Text(HTMLParser):
    """Text content and the elements of a page."""
    def __init__(self, source):
        super().__init__()
        self.text, self.metas, self.tags, self.criteria, self._in = [], {}, [], [], False
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        a = dict(attrs)
        if tag == "meta" and "name" in a:
            self.metas[a["name"]] = a.get("content")
        self._in = tag == "li" and a.get("class") == "criterion"
        if self._in:
            self.criteria.append("")

    def handle_endtag(self, tag):
        if tag == "li":
            self._in = False

    def handle_data(self, data):
        self.text.append(data)
        if self._in:
            self.criteria[-1] += data


class Rendered(unittest.TestCase):
    """render_gate.py run on a copy of a gate file in a temp folder."""

    def render(self, name, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path, run(RENDER, path)


class Preferences(unittest.TestCase):
    def test_1_layer_sets_gate_view_html_and_lang_es_build_policy_carries_both(self):
        extra, home, build = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (extra, home, build):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.makedirs(os.path.join(extra, "acme"))
        with open(os.path.join(extra, "acme", "policy.json"), "w") as f:
            json.dump({"gate_view": "html", "lang": "es"}, f)
        layers.set_extra_roots([extra])
        self.addCleanup(layers.set_extra_roots, [])
        composed = layers.compose_policy(ROOT, ["core", "acme"])
        self.assertEqual((composed["gate_view"], composed["lang"]), ("html", "es"))
        out = run(os.path.join(ROOT, "install.py"), "--home", home, "--build", build, "--tools", "claude",
                  "--layers-dir", extra, "--only", "acme")
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(os.path.join(build, "policy.json")) as f:
            built = json.load(f)
        self.assertEqual((built["gate_view"], built["lang"]), ("html", "es"))
        self.assertIn("preferences: gate_view=html lang=es", out.stdout)

    def test_1_with_no_layer_setting_them_the_defaults_are_gate_view_md_and_lang_en(self):
        layers.set_extra_roots([])
        composed = layers.compose_policy(ROOT, ["core"])
        self.assertEqual((composed["gate_view"], composed["lang"]), ("md", "en"))
        self.assertEqual(layers.preferences({}), {"gate_view": "md", "lang": "en"})
        home, build = tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (home, build):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = run(os.path.join(ROOT, "install.py"), "--home", home, "--build", build, "--tools", "claude", "--only", "core")
        self.assertEqual(out.returncode, 0, out.stderr)
        with open(os.path.join(build, "policy.json")) as f:
            built = json.load(f)
        self.assertEqual((built["gate_view"], built["lang"]), ("md", "en"))

    def test_1_dry_run_shows_the_new_skill_and_the_preferences(self):
        home, build = tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (home, build):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = run(os.path.join(ROOT, "install.py"), "--dry-run", "--home", home, "--build", build, "--tools", "claude", "--only", "core")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("skills/visual-guides", out.stdout)
        self.assertIn("preferences: gate_view=md lang=en", out.stdout)

    def test_1_prefs_prints_the_defaults_or_what_the_policy_file_sets(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for content, want in (({"dev_root": "~"}, "gate_view=md\nlang=en\n"),
                              ({"gate_view": "html", "lang": "es"}, "gate_view=html\nlang=es\n")):
            pol = os.path.join(d, "policy.json")
            with open(pol, "w") as f:
                json.dump(content, f)
            env = dict(os.environ, AI_SETUP_POLICY=pol)
            out = run(RENDER, "--prefs", env=env)
            self.assertEqual((out.returncode, out.stdout), (0, want), out.stderr)


class Skill(unittest.TestCase):
    def test_2_skill_is_installed_takes_lang_from_the_preference_and_offers_the_four_templates(self):
        home, build = tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (home, build):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = run(os.path.join(ROOT, "install.py"), "--home", home, "--build", build, "--tools", "claude", "--only", "core")
        self.assertEqual(out.returncode, 0, out.stderr)
        link = os.path.join(home, ".claude", "skills", "visual-guides")
        self.assertTrue(os.path.exists(os.path.join(link, "SKILL.md")), "skill not installed")
        text = read("core", "skills", "visual-guides", "SKILL.md")
        self.assertIn("`lang`", text)
        self.assertIn("render_gate.py --prefs", text)
        self.assertNotIn("Spanish", text)
        for name in NAMES:
            self.assertIn(f"`{name}`", text)
            self.assertTrue(os.path.isfile(os.path.join(TEMPLATES, name + ".html")), name)

    def test_2_each_template_fills_into_one_self_contained_page_with_no_external_url(self):
        for name in NAMES:
            raw = read("core", "skills", "visual-guides", "templates", name + ".html")
            self.assertNotRegex(raw, EXTERNAL, name)
            page = re.sub(r"\{\{(TITLE|BODY|SHA)\}\}", lambda m: {"TITLE": "T", "BODY": "<p>b</p>", "SHA": "ab"}[m.group(1)], raw)
            self.assertNotIn("{{", page, name)
            parsed = Text(page)
            self.assertIn("<style>", page)
            self.assertEqual(parsed.tags.count("html"), 1)
            self.assertIn("prefers-color-scheme", page)
            self.assertEqual("source-sha256" in parsed.metas, name in ("criteria", "plan"), name)

    def test_2_the_plan_template_has_the_css_of_every_part_of_the_plan_page(self):
        css = read("core", "skills", "visual-guides", "templates", "plan.html").split("</style>")[0]
        for selector in (".goal", "svg.flow", ".map", ".before-after", ".matrix", ".keep", ".stale"):
            self.assertIn(selector, css)
        self.assertNotRegex(css, r"url\(", "the stale banner is inline, the CSS needs no url(")

    def test_2_visual_guides_has_the_plan_html_skeleton_written_by_the_agent(self):
        text = read("core", "skills", "visual-guides", "SKILL.md")
        self.assertNotRegex(text, r"only\s+`?render_gate\.py`?")
        self.assertRegex(text, r"\|\s*`plan`\s*\|[^\n]*\|[^\n]*you[^\n]*\|")
        gate = " ".join(text.split("## Gate pages", 1)[1].split("\n## Before handing", 1)[0].split())
        for needle in ("`plan.html`, written by you", "`## Steps`", '<svg class="flow"', '<g data-step="1">', "Paso N", "one text node",
                       'data-map="touched"', 'data-map="untouched"', 'data-map="removed"', "class=\"matrix\"", "class=\"before-after\"",
                       "only when the plan has", "--lint", "--mark-stale", "outdated", "never re-render", "fails `--lint` by design"):
            self.assertIn(needle, gate)

    def test_2_skill_keeps_the_generic_guide_structure(self):
        text = read("core", "skills", "visual-guides", "SKILL.md")
        for part in ("Title + one line", "Step by step", "Real example", "If it fails", "Last line"):
            self.assertIn(part, text)


class Render(Rendered):
    def test_3_criteria_md_renders_a_sibling_html_with_every_criterion_line_verbatim_and_the_md_hash(self):
        path, out = self.render("criteria.md", CRITERIA)
        self.assertEqual(out.returncode, 0, out.stderr)
        html_path = path[:-3] + ".html"
        self.assertEqual(out.stdout.strip(), html_path)
        page = Text(slurp(html_path))
        want = [l.strip() for l in CRITERIA.splitlines() if re.match(r"\d+\. Given", l)]
        self.assertEqual(page.criteria, want)
        self.assertEqual(page.metas["source-sha256"], hashlib.sha256(CRITERIA.encode()).hexdigest())
        self.assertNotIn("not a criterion", "".join(page.criteria))

    def test_3_plan_md_renders_the_bold_success_criteria_lines_verbatim(self):
        path, out = self.render("plan.md", PLAN)
        self.assertEqual(out.returncode, 0, out.stderr)
        page = Text(slurp(path[:-3] + ".html"))
        self.assertEqual(page.criteria, ["1. Given X, when Y, then Z.", "2. Given A, when B, then C."])
        self.assertEqual(page.metas["source-sha256"], hashlib.sha256(PLAN.encode()).hexdigest())
        self.assertNotIn("<svg", slurp(path[:-3] + ".html"))

    def test_3_plan_success_criteria_with_markup_and_non_ascii_stay_verbatim_and_the_hash_is_of_the_bytes(self):
        plan = ("# Plan: x\n**(d) Success criteria (verbatim from criteria.md, slice PR1):**\n"
                "1. Given `a` & <b>b</b>, when **it** runs, then \"ok\" \u00e1\u00f1 holds.\n"
                "  2. Given an indented one, then it holds.\n"
                "**(e) My commits:** n/a.\n3. not a criterion\n## Slices\n- PR1: a\n- PR2: b \u00b7 depends on PR1\n")
        path, out = self.render("plan.md", plan)
        self.assertEqual(out.returncode, 0, out.stderr)
        page = Text(slurp(path[:-3] + ".html"))
        self.assertEqual(page.criteria, [l.strip() for l in plan.splitlines()[2:4]])
        with open(path, "rb") as f:
            self.assertEqual(page.metas["source-sha256"], hashlib.sha256(f.read()).hexdigest())
        raw = slurp(path[:-3] + ".html")
        self.assertEqual((raw.count('<g class="slice">'), raw.count('<path class="arrow"')), (2, 1))

    def test_3_slices_section_gets_a_script_made_svg_with_one_box_per_slice_and_one_arrow_per_dependency(self):
        path, out = self.render("criteria.md", CRITERIA)
        raw = slurp(path[:-3] + ".html")
        svg = raw[raw.index("<svg"):raw.index("</svg>")]
        self.assertEqual(svg.count('<g class="slice">'), 4)
        self.assertEqual(svg.count('<path class="arrow"'), 4)  # PR2<-PR1, PR3<-PR1, PR4<-PR1, PR4<-PR2
        self.assertNotRegex(svg, EXTERNAL)

    def test_3_slices_with_zero_one_and_two_dependencies(self):
        for lines, boxes, arrows in (("- A: x\n", 1, 0), ("- A: x\n- B: y · depends on A\n", 2, 1),
                                     ("- A: x\n- B: y\n- C: z · depends on A and B\n", 3, 2)):
            path, out = self.render("plan.md", "# P\n## Slices\n" + lines)
            raw = slurp(path[:-3] + ".html")
            self.assertEqual((raw.count('<g class="slice">'), raw.count('<path class="arrow"')), (boxes, arrows), lines)

    def test_3_this_tickets_own_slices_shape(self):
        own = "## Slices\n- PR1: criteria 1-3, 6 · core\n- PR2: criteria 4-5 · depends on PR1 · gates\n- PR3: criterion 7 · depends on PR1 · docs\n- PR4: x · depends on PR1 · y\n"
        path, out = self.render("criteria.md", "# C\n" + own)
        raw = slurp(path[:-3] + ".html")
        self.assertEqual((raw.count('<g class="slice">'), raw.count('<path class="arrow"')), (4, 3))

    def test_3_no_slices_section_means_no_svg(self):
        path, out = self.render("criteria.md", "# C\n## Criteria\n1. Given a, then b.\n")
        self.assertNotIn("<svg", slurp(path[:-3] + ".html"))

    def test_3_output_is_deterministic_escaped_and_has_no_external_url(self):
        path, out = self.render("criteria.md", CRITERIA + "\n```\n<script>alert(1)</script>\n```\n")
        first = slurp(path[:-3] + ".html", binary=True)
        run(RENDER, path)
        self.assertEqual(first, slurp(path[:-3] + ".html", binary=True))
        page = first.decode()
        self.assertNotRegex(page, EXTERNAL)
        self.assertNotIn("<script>", page)
        self.assertNotIn("{{", page)

    def test_3_a_missing_or_non_utf8_md_exits_2_with_one_line_and_no_traceback(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        missing = run(RENDER, os.path.join(d, "criteria.md"))
        bad = os.path.join(d, "plan.md")
        with open(bad, "wb") as f:
            f.write(b"# P\n\xff\xfe\n")
        broken = run(RENDER, bad)
        for out in (missing, broken):
            self.assertEqual(out.returncode, 2)
            self.assertNotIn("Traceback", out.stderr)
            self.assertEqual(len(out.stderr.strip().splitlines()), 1, out.stderr)

    def test_3_a_wrapped_criterion_stays_one_item_joined_with_one_space(self):
        path, out = self.render("criteria.md", "# C\n## Criteria\n1. Given a long line\n   that wraps, then it holds.\n2. Given b, then c.\n")
        page = Text(slurp(path[:-3] + ".html"))
        self.assertEqual(page.criteria, ["1. Given a long line that wraps, then it holds.", "2. Given b, then c."])

    def test_3_a_utf8_bom_keeps_the_first_heading_and_the_hash_covers_the_raw_bytes(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "criteria.md")
        raw = "\ufeff# Criteria: bom\n## Criteria\n1. Given a, then b.\n".encode("utf-8")
        with open(path, "wb") as f:
            f.write(raw)
        self.assertEqual(run(RENDER, path).returncode, 0)
        page = slurp(path[:-3] + ".html")
        self.assertIn("<h1>Criteria: bom</h1>", page)
        self.assertEqual(Text(page).metas["source-sha256"], hashlib.sha256(raw).hexdigest())

    def test_3_only_criteria_md_and_plan_md_can_be_rendered(self):
        path, out = self.render("notes.md", "# N\n")
        self.assertEqual(out.returncode, 2)
        self.assertFalse(os.path.exists(path[:-3] + ".html"))


def html_mentions(texts):
    """The files (name -> text) that mention a .html."""
    return [name for name, text in texts.items() if re.search(r"\.html\b", text)]


class AgentsReadTheMarkdown(unittest.TestCase):
    READERS = ("core/agents/sub-tester.md", "core/agents/sub-review.md", "core/agents/sub-review-xprov.md",
               "core/skills/ai-audit/SKILL.md", "core/skills/ai-audit/audit.py")

    def test_6_sub_tester_sub_review_sub_review_xprov_and_ai_audit_never_read_a_gate_html(self):
        self.assertEqual(html_mentions({rel: read(*rel.split("/")) for rel in self.READERS}), [])
        for rel in self.READERS[:3]:
            self.assertIn("criteria.md", read(*rel.split("/")), rel)
        self.assertIn("criteria.md", read("core", "skills", "ai-audit", "audit.py"))

    def test_6_the_check_fails_when_a_reader_is_made_to_read_criteria_html(self):
        """Mutation on in-memory copies: the real files are never touched."""
        for rel in self.READERS:
            text = read(*rel.split("/"))
            self.assertEqual(html_mentions({rel: text}), [], rel)
            self.assertEqual(html_mentions({rel: text + "\nread criteria.html\n"}), [rel])
            self.assertEqual(html_mentions({rel: text + "\nopen plan.html"}), [rel])

    def test_6_audit_does_not_count_a_handoff_that_only_has_criteria_html(self):
        dev, repo = tempfile.mkdtemp(), tempfile.mkdtemp()
        for d in (dev, repo):
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        os.makedirs(os.path.join(dev, "handoffs", "x"))
        with open(os.path.join(dev, "handoffs", "x", "criteria.html"), "w") as f:
            f.write("<p>1. Given a, then b.</p>")
        audit = os.path.join(ROOT, "core", "skills", "ai-audit", "audit.py")
        out = run(audit, "--dev-root", dev, repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"criteria: none")


if __name__ == "__main__":
    unittest.main()
