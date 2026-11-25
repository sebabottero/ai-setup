"""Model split: ticket-flow plans on the strong model and offers a switch to the balanced model at Gate 1.
One test per criterion of the ticket, named after it. Wording checks on SKILL.md sections (prompt text cannot be
behaviour-tested), plus a behavioural check of `run_json.py update --session auto` across two sessions (criterion 6)."""
import json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import outcomes

TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
RUN_JSON = os.path.join(ROOT, "core", "guard", "run_json.py")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def section(text, start):
    """Text from the `## ` heading line starting with `start` up to the next `## ` heading; fails clearly if absent."""
    m = re.search(r"^" + re.escape(start) + r".*$", text, re.M)
    if not m:
        raise AssertionError(f"ticket-flow/SKILL.md has no heading starting with: {start}")
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.start():m.end() + nxt.start()] if nxt else text[m.start():]


def flat(text):
    """Lowercased, whitespace collapsed, so line wrapping does not matter."""
    return " ".join(text.lower().split())


def paragraph(gate, marker):
    """The Gate 1 text from the "Model switch" marker to the end of the section (flattened)."""
    i = gate.find(marker)
    if i < 0:
        raise AssertionError(f"Gate 1 section lacks a paragraph named: {marker}")
    return flat(gate[i:])


class ModelSplit(unittest.TestCase):
    def setUp(self):
        self.text = read(TICKET_FLOW)

    def assert_all(self, text, where, *needles):
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{where} lacks: {needle}")

    def test_1_given_the_ticket_flow_skill_before_gate_1_runs_on_the_strong_model_and_from_stage_2_on_the_balanced_model(self):
        models = flat(section(self.text, "## Models"))
        self.assert_all(models, "section Models",
                        "before gate 1 (0a, 0b, plan, plan critic) the orchestrator runs on the strong model",
                        "from stage 2 on it runs on the balanced model")
        build = flat(section(self.text, "## 2 · Build"))
        self.assert_all(build, "section 2 · Build",
                        "the planning decisions were made before gate 1",
                        "after a switch the orchestrator is on the balanced model too",
                        'with "keep" it stays where it is')

    def test_2_given_the_ok_at_gate_1_the_switch_offer_goes_handoff_clear_model_prompt_and_keep_goes_straight_to_stage_2(self):
        gate = section(self.text, "## ⛔ GATE 1")
        para = paragraph(gate, "Model switch")
        self.assert_all(para, "Gate 1 Model switch paragraph", "model picker",
                        'if i say "keep", go straight to stage 2 as today.')
        gate_flat = flat(gate)
        scope_add = gate_flat.find("scope.py add")
        self.assertGreaterEqual(scope_add, 0, "Gate 1 lacks: scope.py add")
        self.assertLess(scope_add, gate_flat.index("model switch"),
                        "Gate 1: `scope.py add` must come before the Model switch paragraph")
        order = [(n, para.find(n)) for n in ("scoped approvals", "run_json", "handoff.md", "/clear", "/model", "copy-paste")]
        for name, idx in order:
            self.assertGreaterEqual(idx, 0, f"Model switch paragraph lacks: {name}")
        for (a, ia), (b, ib) in zip(order, order[1:]):
            self.assertLess(ia, ib, f"Model switch paragraph: {a} must come before {b}")

    def test_3_given_the_handoff_md_it_names_every_field_stage_2_needs(self):
        para = paragraph(section(self.text, "## ⛔ GATE 1"), "Model switch")
        self.assert_all(para, "Gate 1 handoff.md paragraph", "ticket", "worktree", "branch", "base", "allowlist",
                        "out of scope", "criteria.md", "plan.md", "plan-critic.md", "run.json", "slice", "`none`",
                        "cross-review", "`off`", "gate_view", "next stage")

    def test_4_given_the_short_route_there_is_no_switch_offer_and_the_run_stays_on_the_sessions_model(self):
        short = flat(section(self.text, "## Short route"))
        self.assert_all(short, "section Short route", "no switch offer", "session's model")

    def test_5_given_already_balanced_or_no_model_switch_gate_1_makes_no_offer_and_stage_2_starts_as_today(self):
        para = paragraph(section(self.text, "## ⛔ GATE 1"), "Model switch")
        self.assert_all(para, "Gate 1 Model switch paragraph", "already on the balanced model", "unsure",
                        "no model switch", "no offer", "stage 2 starts as today", "own model name")

    def test_6_given_the_run_journal_session_auto_in_the_new_session_adds_its_id_so_run_json_lists_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = os.path.realpath(tmp)
            sessions = os.path.join(tmp, "sessions")
            env = {**os.environ, "AI_SETUP_SESSIONS_DIR": sessions}
            ticket = "demo-ticket"

            def call(session_id):
                os.environ["AI_SETUP_SESSIONS_DIR"] = sessions
                try:
                    outcomes.remember_session(tmp, session_id)
                finally:
                    del os.environ["AI_SETUP_SESSIONS_DIR"]
                r = subprocess.run([sys.executable, "-I", RUN_JSON, "update", ticket, "--dev-root", tmp, "--session", "auto"],
                                   cwd=tmp, env=env, capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(os.path.join(tmp, "handoffs", ticket, "run.json"), encoding="utf-8") as f:
                    return json.load(f)["sessions"]

            self.assertEqual(call("session-a"), ["session-a"])
            self.assertEqual(call("session-b"), ["session-a", "session-b"])
            self.assertEqual(call("session-b"), ["session-a", "session-b"], "a repeated session id must not be duplicated")

        record = flat(section(self.text, "## Run record"))
        self.assert_all(record, "section Run record", "model switch", "--session auto", "before any stage 2 work",
                        "lists both sessions")


if __name__ == "__main__":
    unittest.main()
