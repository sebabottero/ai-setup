import json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude", "hooks"))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude"))
import context_notice, usage_report


def turn(context, model="claude-opus-5-5"):
    return {"type": "assistant", "message": {"model": model, "usage": {
        "input_tokens": 10, "cache_read_input_tokens": context - 10, "cache_creation_input_tokens": 0,
        "output_tokens": 5}}}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def transcript(self, *contexts):
        path = os.path.join(self.dir, "t.jsonl")
        with open(path, "w") as f:
            for c in contexts:
                f.write(json.dumps(turn(c)) + "\n")
        return path


class GuardReport(unittest.TestCase):
    def test_summary_counts_decisions_and_top_rules(self):
        path = os.path.join(tempfile.mkdtemp(), "guard.log")
        with open(path, "w") as f:
            f.write("2026-10-28T10:00:00\tbash\task\tgit push *\n2026-10-28T10:01:00\tbash\task\tgit push *\n"
                    "2026-10-28T10:02:00\tbash\tdeny\tsecret\n2026-10-28T10:03:00\tbash\tallow\t-\nnot a log line\n")
        s = usage_report.guard_summary(path)
        self.assertEqual((s["ask"], s["deny"], s["allow"]), (2, 1, 1))
        self.assertEqual(s["rules"].most_common(1), [("git push *", 2)])

    def test_missing_log_is_none(self):
        self.assertIsNone(usage_report.guard_summary(os.path.join(tempfile.mkdtemp(), "nope.log")))


class ContextNotice(Base):
    def notice(self, path, session="s1"):
        return context_notice.notice(path, session, self.dir)

    def test_silent_below_threshold(self):
        self.assertIsNone(self.notice(self.transcript(40_000, 149_000)))

    def test_warns_above_threshold_once(self):
        path = self.transcript(120_000, 160_000)
        self.assertIn("160k", self.notice(path))
        self.assertIsNone(self.notice(path))  # same band: no nagging

    def test_warns_again_after_next_step(self):
        self.assertIn("160k", self.notice(self.transcript(160_000)))
        self.assertIn("215k", self.notice(self.transcript(215_000)))

    def test_sessions_are_independent(self):
        path = self.transcript(160_000)
        self.assertIsNotNone(self.notice(path, "a"))
        self.assertIsNotNone(self.notice(path, "b"))

    def test_bad_input_is_silent(self):
        self.assertIsNone(self.notice(os.path.join(self.dir, "missing.jsonl")))
        self.assertIsNone(self.notice(None))

    def test_output_reaches_the_model(self):
        out = context_notice.output("Context is 160k tokens.")
        extra = out["hookSpecificOutput"]
        self.assertEqual(extra["hookEventName"], "UserPromptSubmit")
        self.assertIn("160k", extra["additionalContext"])
        self.assertIn("telling the user", extra["additionalContext"].lower())
        self.assertEqual(out["systemMessage"], "Context is 160k tokens.")


class UsageReport(Base):
    def test_summary(self):
        path = self.transcript(40_000, 200_000)
        s = usage_report.summarize([path])
        self.assertEqual(s["sessions"], 1)
        self.assertEqual(s["over_150k"], 1)
        self.assertEqual(s["models"]["claude-opus-5-5"], 2)
        self.assertEqual(s["max_context"], 200_000)


if __name__ == "__main__":
    unittest.main()
