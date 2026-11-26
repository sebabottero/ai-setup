"""Gate view: `render_gate.py --check`, and grillme / ticket-flow using the HTML view only when `gate_view` is html.
One test per criterion of the ticket, named after it. Criteria 1, 3, 4 and 5."""
import hashlib, json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import layers

RENDER = os.path.join(ROOT, "core", "guard", "render_gate.py")
CRITERIA = "# Criteria: sample\n## Criteria\n1. Given a, when b, then c.\n## Done\nAll pass.\n"


def run(*args, env=None):
    return subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, env=env)


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def section(text, start, end=None):
    """Text from the heading line starting with `start` up to the next heading that starts with `end` (or the next `## `)."""
    i = text.index(start)
    m = re.search(r"^## " if end is None else "^" + re.escape(end), text[i + len(start):], re.M)
    return text[i:i + len(start) + m.start()] if m else text[i:]


def flat(text):
    return " ".join(text.split())


MD = "# Criteria: sample\n## Goal\nOne line.\n## Criteria\n1. Given a, when b, then c.\n2. Given d, when e, then f.\n## Done\nAll pass.\n"
SLICES = "## Slices\n- PR1: criteria 1 · first\n- PR2: criteria 2 · depends on PR1\n"
PLAN = "# Plan: sample\n## Steps\n1. Tests first.\n2. Code.\n"
KEEP = ('<section class="keep"><div data-keep="irreversible">{irreversible}</div><div data-keep="risks">{risks}</div>'
        '<div data-keep="deviations">{deviations}</div></section>')
SVG = '<svg class="slices" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
CARDS = "".join(f'<article class="card" data-ref="C{n}"><b class="ref">C{n}</b><p class="given">a</p><p class="when">b</p><p class="then">c</p></article>' for n in (1, 2))


def body(goal='<p class="goal">One line.</p>', scope='<section class="scope"><div class="in">in</div><div class="out">out</div></section>',
         cards=CARDS, keep=None, svg=SVG, extra=""):
    keep = KEEP.format(irreversible="none", risks="none", deviations="none") if keep is None else keep
    return f'{goal}{scope}<section class="cards">{cards}</section>{keep}{svg}{extra}'


def page(md, content, head=""):
    sha = hashlib.sha256(md.encode()).hexdigest()
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="source-sha256" content="{sha}">{head}'
            f'<title>t</title><style>.x{{color:#C00}}</style></head><body><main>{content}</main></body></html>')


class Lint(unittest.TestCase):
    """`render_gate.py --lint <page.html>`: exit 0 silent, exit 1 with one line per failure, exit 2 on bad use."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def lint(self, content, md=MD, head="", name="criteria", plan=None):
        self.write(name + ".md", md)
        if plan is not None:
            self.write("plan.md", plan)
        return run(RENDER, "--lint", self.write(name + ".html", page(md, content, head)))

    def fails(self, out, *needles):
        self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
        lines = out.stderr.strip().splitlines()
        self.assertEqual(len(lines), len(needles), out.stderr)
        for line, needle in zip(lines, needles):
            self.assertTrue(line.startswith("lint: ") and needle in line, line)

    def test_4_a_good_page_exits_0_and_prints_nothing(self):
        out = self.lint(body())
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "", ""))

    def test_4_an_external_url_fails_with_one_line_each(self):
        for bad in ('<a href="https://cdn.example/x.js">x</a>', '<p>http://example.com</p>', '<img src="a.png">'):
            self.fails(self.lint(body(extra=bad)), "external URL")
        self.fails(self.lint(body(), head='<link rel="stylesheet" href="a.css">'), "external URL")
        self.fails(self.lint(body(), head='<style>@import "a.css";</style>'), "external URL")

    def test_4_a_page_without_an_inline_svg_fails(self):
        self.fails(self.lint(body(svg="")), "no inline <svg>")

    def test_4_a_reference_that_is_not_in_the_md_fails_but_hex_colours_and_the_sha_do_not_count(self):
        self.fails(self.lint(body(extra="<p>see C9</p>")), "C9 is not a criterion in criteria.md")
        ok = self.lint(body(extra='<p style="color:#C00">C1 and C2</p>'), head='<meta name="x" content="C77">')
        self.assertEqual((ok.returncode, ok.stderr), (0, ""))

    def test_4_a_bold_criteria_line_counts_as_a_criteria_heading_like_in_the_converter(self):
        md = MD.replace("## Criteria", "**Criteria**")
        out = self.lint(body(), md=md)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        self.fails(self.lint(body(extra="<p>C9</p>"), md=md), "C9 is not a criterion")

    def test_4_a_paso_reference_is_checked_against_plan_md(self):
        self.assertEqual(self.lint('<p>Paso 1 and Paso 2</p>' + SVG, md=PLAN, name="plan", plan=PLAN).returncode, 0)
        self.fails(self.lint('<p>Paso 7</p>' + SVG, md=PLAN, name="plan", plan=PLAN), "Paso 7 is not a step in plan.md")

    def test_4_a_missing_sibling_md_is_one_line(self):
        path = self.write("criteria.html", page(MD, body()))
        out = run(RENDER, "--lint", path)
        self.fails(out, "criteria.md is missing")

    def test_4_a_source_sha256_that_differs_fails(self):
        self.write("criteria.md", MD)
        path = self.write("criteria.html", page(MD + "extra\n", body()))
        self.fails(run(RENDER, "--lint", path), "source-sha256 differs from criteria.md")

    def test_4_bad_use_exits_2(self):
        self.assertEqual(run(RENDER, "--lint").returncode, 2)
        self.assertEqual(run(RENDER, "--lint", self.write("notes.html", "x")).returncode, 2)

    def test_4_sha_prints_the_hash_of_the_md_bytes(self):
        md = self.write("criteria.md", MD)
        out = run(RENDER, "--sha", md)
        self.assertEqual(out.stdout.strip(), hashlib.sha256(MD.encode()).hexdigest())
        self.assertEqual(run(RENDER, "--sha", md + ".none").returncode, 2)

    def test_1_a_page_with_goal_scope_one_card_per_criterion_and_the_slice_svg_passes(self):
        out = self.lint(body(), md=MD + SLICES)
        self.assertEqual((out.returncode, out.stderr), (0, ""))

    def test_1_a_missing_goal_scope_card_or_slice_svg_fails(self):
        self.fails(self.lint(body(goal="")), "no .goal")
        self.fails(self.lint(body(scope="")), "no .scope")
        self.fails(self.lint(body(cards=CARDS.split("</article>")[0] + "</article>")), "no card for C2")
        self.fails(self.lint(body(svg='<svg viewBox="0 0 1 1"></svg>'), md=MD + SLICES), "no svg.slices")

    def test_1_the_structure_is_checked_only_on_criteria_html(self):
        self.assertEqual(self.lint('<p>x</p>' + SVG, md=PLAN, name="plan").returncode, 0)

    def test_3_the_keep_block_and_its_three_parts_must_exist_with_text(self):
        self.fails(self.lint(body(keep="<p>nothing</p>")), "no .keep", "no data-keep=irreversible", "no data-keep=risks", "no data-keep=deviations")
        for part in ("irreversible", "risks", "deviations"):
            parts = dict(irreversible="a", risks="b", deviations="c")
            blank = KEEP.format(**{**parts, part: ""})
            self.fails(self.lint(body(keep=blank)), f"data-keep={part} is empty")
            gone = blank.replace(f'<div data-keep="{part}"></div>', "")
            self.fails(self.lint(body(keep=gone)), f"no data-keep={part}")
        full = KEEP.format(irreversible="push to origin", risks="r", deviations="none")
        self.assertEqual(self.lint(body(keep=full)).returncode, 0)

    def test_3_5_the_skills_say_never_dropped_lint_retry_once_and_the_one_line_fallback(self):
        visual = flat(section(read("core", "skills", "visual-guides", "SKILL.md"), "## Gate pages"))
        grill = flat(read("core", "skills", "grillme", "SKILL.md").split("\n## Closing", 1)[1])
        for needle in ("never dropped", "--lint", "--sha", "data-keep"):
            self.assertIn(needle, visual)
        for needle in ("--lint", "once", "render_gate.py <criteria.md>", "visual summary failed", "never dropped"):
            self.assertIn(needle, grill)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.md = os.path.join(self.tmp.name, "criteria.md")
        self.html = os.path.join(self.tmp.name, "criteria.html")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(CRITERIA)

    def test_4_given_an_html_whose_source_sha256_differs_from_its_md_check_exits_non_zero(self):
        self.assertEqual(run(RENDER, self.md).returncode, 0)
        fresh = run(RENDER, "--check", self.md)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        with open(self.md, "a", encoding="utf-8") as f:
            f.write("2. Given d, when e, then f.\n")
        stale = run(RENDER, "--check", self.md)
        self.assertEqual(stale.returncode, 1)
        self.assertEqual(len(stale.stderr.strip().splitlines()), 1)
        self.assertIn("differs", stale.stderr)

    def test_4_check_accepts_the_html_path_too(self):
        run(RENDER, self.md)
        self.assertEqual(run(RENDER, "--check", self.html).returncode, 0)
        with open(self.md, "a", encoding="utf-8") as f:
            f.write("x\n")
        self.assertEqual(run(RENDER, "--check", self.html).returncode, 1)

    def test_4_check_is_stale_when_the_html_is_missing_or_has_no_hash(self):
        missing = run(RENDER, "--check", self.md)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("missing", missing.stderr)
        self.assertEqual(run(RENDER, "--check", self.html).returncode, 1)
        with open(self.html, "w", encoding="utf-8") as f:
            f.write("<html><head></head><body></body></html>")
        nohash = run(RENDER, "--check", self.md)
        self.assertEqual(nohash.returncode, 1)
        self.assertIn("source-sha256", nohash.stderr)

    def test_4_check_on_an_unreadable_file_is_one_line_and_exit_1(self):
        run(RENDER, self.md)
        with open(self.html, "wb") as f:
            f.write(b"\xff\xfe not utf-8")
        bad = run(RENDER, "--check", self.md)
        self.assertEqual(bad.returncode, 1)
        self.assertNotIn("Traceback", bad.stderr)
        self.assertEqual(len(bad.stderr.strip().splitlines()), 1)

    def test_4_check_refuses_a_file_that_is_not_criteria_or_plan(self):
        other = os.path.join(self.tmp.name, "notes.md")
        with open(other, "w") as f:
            f.write("x")
        self.assertEqual(run(RENDER, "--check", other).returncode, 2)
        self.assertEqual(run(RENDER, "--check").returncode, 2)


class Prefs(unittest.TestCase):
    """Extra (no criterion): an unknown gate_view falls back to md, in one place."""
    def test_extra_gate_view_is_lowercased_and_an_unknown_value_falls_back_to_md(self):
        self.assertEqual(layers.preferences({"gate_view": "HTML"})["gate_view"], "html")
        self.assertEqual(layers.preferences({"gate_view": "htlm"})["gate_view"], "md")
        self.assertEqual(layers.preferences({"gate_view": 3})["gate_view"], "md")
        self.assertEqual(layers.preferences({"gate_view": None})["gate_view"], "md")
        self.assertEqual(layers.compose_policy(ROOT, ["core"])["gate_view"] in layers.GATE_VIEWS, True)
        self.assertEqual(layers.preferences({})["gate_view"], "md")

    def test_extra_install_warns_on_an_unknown_gate_view(self):
        with tempfile.TemporaryDirectory() as extra, tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as build:
            os.makedirs(os.path.join(extra, "acme"))
            with open(os.path.join(extra, "acme", "policy.json"), "w") as f:
                json.dump({"gate_view": "htlm"}, f)
            out = run(os.path.join(ROOT, "install.py"), "--home", home, "--build", build, "--tools", "claude",
                      "--layers-dir", extra, "--only", "acme")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("preferences: gate_view=md", out.stdout)
            self.assertIn("htlm", out.stdout + out.stderr)
            self.assertIn("warning", out.stdout + out.stderr)

    def test_extra_compose_policy_install_log_and_prefs_agree(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "one"))
            raw = {"gate_view": "HTML", "lang": "es"}
            with open(os.path.join(tmp, "one", "policy.json"), "w") as f:
                json.dump(raw, f)
            composed = layers.compose_policy(tmp, ["one"])
            self.assertEqual(composed["gate_view"], "html")
            self.assertEqual(layers.preferences(composed), {"gate_view": "html", "lang": "es"})
            policy = os.path.join(tmp, "raw.json")
            with open(policy, "w") as f:
                json.dump(raw, f)
            out = run(RENDER, "--prefs", env={**os.environ, "AI_SETUP_POLICY": policy})
            self.assertEqual(out.stdout.split(), ["gate_view=html", "lang=es"])
            self.assertEqual(out.stderr, "")
            with open(policy, "w") as f:
                json.dump({"gate_view": "htlm"}, f)
            bad = run(RENDER, "--prefs", env={**os.environ, "AI_SETUP_POLICY": policy})
            self.assertIn("gate_view=md", bad.stdout)
            self.assertEqual(len(bad.stderr.strip().splitlines()), 1)
            self.assertIn("htlm", bad.stderr)
            for value in (None, 3):
                with open(policy, "w") as f:
                    json.dump({"gate_view": value}, f)
                odd = run(RENDER, "--prefs", env={**os.environ, "AI_SETUP_POLICY": policy})
                self.assertEqual(odd.returncode, 0, odd.stderr)
                self.assertIn("gate_view=md", odd.stdout)
                self.assertEqual(len(odd.stderr.strip().splitlines()), 1)


class Wording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.grill = flat(read("core", "skills", "grillme", "SKILL.md").split("\n## Closing", 1)[1])  # last section: it holds a code fence with ## lines
        ticket = read("core", "skills", "ticket-flow", "SKILL.md")
        cls.zero_a = flat(section(ticket, "## 0a"))
        cls.gate1 = flat(section(ticket, "## ⛔ GATE 1"))
        cls.visual = read("core", "skills", "visual-guides", "SKILL.md")

    def test_4_with_gate_view_html_grillme_and_ticket_flow_run_check_and_re_render_before_the_gate(self):
        for name, text in (("grillme closing", self.grill), ("0a", self.zero_a), ("gate 1", self.gate1)):
            for needle in ("gate_view", "--prefs", "--check", "re-render"):
                self.assertIn(needle, text, f"{name} lacks {needle}")

    def test_4_a_failing_or_empty_prefs_read_means_md(self):
        for name, text in (("grillme closing", self.grill), ("0a", self.zero_a), ("gate 1", self.gate1)):
            self.assertIn("fails or prints nothing", text, name)

    def test_4_visual_guides_says_gates_check_freshness_with_check(self):
        self.assertIn("--check", section(self.visual, "## Gate pages"))

    def test_5_with_gate_view_html_the_gate_message_is_at_most_3_lines_plus_open_path(self):
        for name, text in (("grillme closing", self.grill), ("gate 1", self.gate1)):
            self.assertIn("at most 3 lines", text, name)
            self.assertIn("! open <absolute path to", text, name)
        self.assertIn("criteria.html", self.grill)
        self.assertIn("plan.html", self.gate1)
        self.assertIn("! open <absolute path to criteria.html>", self.zero_a)

    def test_5_gate_1_layout_has_verdict_questions_and_cross_review_or_critic_lines(self):
        for needle in ("Single PR", "Risks / open questions", "answers in chat", "cross-provider review line",
                       "also says the unresolved critic findings and extras are in `plan.html`"):
            self.assertIn(needle, self.gate1)

    def test_5_with_gate_view_md_no_html_is_written_and_the_gate_is_unchanged(self):
        for name, text in (("grillme closing", self.grill), ("0a", self.zero_a), ("gate 1", self.gate1)):
            self.assertRegex(text, r"gate_view[=` ]+md`?.{0,80}no `\.html` is written", name)
            self.assertIn("unchanged", text, name)

    def test_5_the_short_route_uses_criteria_html_only(self):
        self.assertIn("criteria.html", self.zero_a)
        self.assertRegex(self.zero_a, r"no `plan\.md`.{0,80}criteria\.html|criteria\.html.{0,80}no `plan\.md`")


if __name__ == "__main__":
    unittest.main()
