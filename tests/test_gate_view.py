"""Gate view: `render_gate.py --check`, and grillme / ticket-flow using the HTML view only when `gate_view` is html.
One test per criterion of the ticket, named after it. Criteria 4 and 5."""
import json, os, re, subprocess, sys, tempfile, unittest

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
