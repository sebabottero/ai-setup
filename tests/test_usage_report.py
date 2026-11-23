import contextlib, datetime, io, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude"))
import usage_report

NOW = datetime.datetime(2026, 11, 20, 12, 0, 0)  # a Friday, ISO week 2026-W47


TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    TMP.cleanup()


def write(name, lines):
    path = os.path.join(tempfile.mkdtemp(dir=TMP.name), name)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


def guard_line(day, hour, decision, rule="git push *"):
    return f"2026-11-{day:02d}T{hour:02d}:00:00\tbash\t{decision}\t{rule}"


def action(day, session, what, cmd, rule="git push *", hour=10):
    return f"2026-11-{day:02d}T{hour:02d}:00:00\t{session}\tMEDIUM\t{what}\t{rule}\t{cmd}"


class AskReport(unittest.TestCase):
    def report(self, guard, actions, days=14):
        return "\n".join(usage_report.ask_report(days, NOW, write("g.log", guard), write("a.log", actions)))

    def test_asks_per_day(self):
        out = self.report([guard_line(18, 9, "ask"), guard_line(18, 10, "ask"), guard_line(19, 9, "ask"),
                           guard_line(19, 10, "allow")], [])
        self.assertIn("Asks per day (3 in 2 days with asks, avg 1.5): 11-18 2, 11-19 1", out)

    def test_ask_rate_per_iso_week(self):
        out = self.report([guard_line(10, 9, "ask"), guard_line(11, 9, "allow"), guard_line(12, 9, "allow"),
                           guard_line(13, 9, "allow"), guard_line(18, 9, "ask"), guard_line(19, 9, "ask")], [])
        self.assertIn("2026-W46 25% (1/4)", out)
        self.assertIn("2026-W47 100% (2/2)", out)

    def test_approval_rate_links_by_session_and_command_and_keeps_unknown_apart(self):
        actions = [action(18, "s1", "asked", "git push a"), action(18, "s1", "approved", "git push a"),
                   action(18, "s1", "asked", "git push b"), action(19, "s1", "declined", "git push b"),  # stamped later
                   action(18, "s2", "asked", "git push a"), action(18, "s2", "unknown", "git push a"),
                   action(18, "s3", "asked", "git push c"),                                            # unresolved
                   action(18, "s3", "ran", "ls", rule="-")]
        out = self.report([], actions)
        self.assertIn("Approval rate: 50% (1 approved / 2 decided); unknown 1, unresolved 1 (of 4 asks", out)

    def test_old_log_without_outcomes_is_all_unresolved(self):
        out = self.report([], [action(18, "s1", "asked", "git push a"), action(18, "s1", "asked", "git push b")])
        self.assertIn("Approval rate: n/a (no decided asks); unknown 0, unresolved 2", out)

    def test_decision_time_is_the_ask_time_not_the_decline_time(self):
        # asked before the window, declined stamped inside it: not counted
        actions = [action(1, "s1", "asked", "git push a"), action(19, "s1", "declined", "git push a")]
        out = self.report([], actions, days=7)
        self.assertIn("unresolved 0 (of 0 asks", out)

    def test_top_5_ask_rules_ignore_allow_and_deny(self):
        guard = [guard_line(18, h, "ask", f"rule{i}") for i in range(7) for h in range(1, i + 2)]
        guard += [guard_line(18, 20, "deny", "secret"), guard_line(18, 21, "allow", "-")]
        out = self.report(guard, [])
        top = [l for l in out.splitlines() if l.startswith("Top ask rules")][0]
        self.assertEqual(top, "Top ask rules: rule6 7, rule5 6, rule4 5, rule3 4, rule2 3")

    def test_missing_logs_say_so(self):
        gone = os.path.join(tempfile.mkdtemp(dir=TMP.name), "nope.log")
        out = "\n".join(usage_report.ask_report(7, NOW, gone, gone))
        self.assertIn("no guard log yet", out)
        self.assertIn("Approval rate: no action log yet", out)

    def test_rotated_action_log_is_flagged(self):
        a = write("a.log", [action(18, "s1", "asked", "git push a")])
        open(a + ".1", "w").close()
        out = "\n".join(usage_report.ask_report(14, NOW, write("g.log", []), a))
        self.assertIn("the log rotated at 1 MB", out)


class Main(unittest.TestCase):
    def run_main(self, days):
        env = {"HOME": tempfile.mkdtemp(dir=TMP.name), "AI_SETUP_GUARD_LOG": write("g.log", [
            guard_line(1, 9, "ask"), guard_line(18, 9, "ask"), guard_line(18, 10, "allow"), guard_line(19, 9, "deny", "secret")]),
            "AI_SETUP_ACTIONS_LOG": write("a.log", [action(18, "s1", "asked", "git push a"),
                                                  action(18, "s1", "approved", "git push a")])}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                usage_report.main(days, NOW)
            return buf.getvalue()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_main_prints_every_ask_line_and_the_guard_line_honours_the_window(self):
        out = self.run_main(14)
        self.assertIn("Guard (last 14 days): 1 allowed, 1 asked, 1 denied.", out)  # the ask on 11-01 is outside
        for head in ("Asks per day (1 in 1 days", "Ask rate per week", "Top ask rules: git push * 1",
                     "Approval rate: 100% (1 approved / 1 decided)"):
            self.assertIn(head, out)

    def test_main_without_days_says_all_time(self):
        self.assertIn("Guard (all time): 1 allowed, 2 asked, 1 denied.", self.run_main(None))


if __name__ == "__main__":
    unittest.main()
