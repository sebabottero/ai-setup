import contextlib, datetime, io, json, os, subprocess, sys, tempfile, unittest

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


class TicketReport(unittest.TestCase):
    def setUp(self):
        self.dev = tempfile.mkdtemp(dir=TMP.name)
        self.projects = tempfile.mkdtemp(dir=TMP.name)

    def transcript(self, session, turns):
        """turns: [(timestamp, input, cache_read, output)] assistant turns of one session."""
        d = os.path.join(self.projects, "-proj")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, session + ".jsonl"), "w") as f:
            for ts, i, c, o in turns:
                f.write(json.dumps({"type": "assistant", "timestamp": ts, "message": {
                    "model": "m", "usage": {"input_tokens": i, "cache_read_input_tokens": c, "output_tokens": o}}}) + "\n")

    def run_json(self, slug, run):
        os.makedirs(os.path.join(self.dev, "handoffs", slug))
        with open(os.path.join(self.dev, "handoffs", slug, "run.json"), "w") as f:
            json.dump(run, f)

    def report(self, slug="t1"):
        return "\n".join(usage_report.ticket_report(slug, self.dev, self.projects))

    def test_prints_tokens_turns_and_wall_time_of_the_ticket_sessions(self):
        self.transcript("s1", [("2026-11-20T10:00:00Z", 100, 400, 50), ("2026-11-20T10:30:00Z", 10, 0, 40)])
        self.transcript("s2", [("2026-11-20T12:00:00Z", 5, 5, 5), ("2026-11-20T12:15:00Z", 0, 0, 5)])
        self.transcript("other", [("2026-11-20T10:00:00Z", 999, 999, 999)])
        self.run_json("t1", {"ticket": "t1", "sessions": ["s1", "s2"], "branch": "ai/x", "start": "2026-11-20T09:00:00", "end": None})
        out = self.report()
        self.assertIn("sessions: 2 of 2 with a transcript", out)
        self.assertIn("tokens: 620 (520 input incl. cache, 100 output)", out)
        self.assertIn("turns: 4", out)
        self.assertIn("wall time: 45m", out)

    def test_missing_transcript_and_missing_ids_are_said_not_guessed(self):
        self.transcript("s1", [("2026-11-20T10:00:00Z", 1, 0, 1), ("2026-11-20T10:10:00Z", 1, 0, 1)])
        self.run_json("t1", {"ticket": "t1", "sessions": ["s1", "gone"]})
        out = self.report()
        self.assertIn("sessions: 1 of 2 with a transcript", out)
        self.assertIn("no transcript for: gone (not counted)", out)
        self.run_json("t2", {"ticket": "t2", "sessions": []})
        self.assertIn("no session ids in run.json", self.report("t2"))
        self.assertNotIn("tokens:", self.report("t2"))

    def test_a_message_repeated_on_every_content_block_line_counts_once(self):
        d = os.path.join(self.projects, "-proj")
        os.makedirs(d)
        with open(os.path.join(d, "dup.jsonl"), "w") as f:
            for block in ({"type": "thinking"}, {"type": "text"}, {"type": "tool_use", "name": "Bash"}):
                f.write(json.dumps({"type": "assistant", "timestamp": "2026-11-20T10:00:00Z", "message": {
                    "id": "msg_1", "model": "m", "content": [block],
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7}}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"model": "m", "usage": {"input_tokens": 1, "output_tokens": 1}}}) + "\n")
        s = usage_report.summarize([os.path.join(d, "dup.jsonl")])
        self.assertEqual((s["turns"], s["input_tokens"], s["output_tokens"]), (2, 101, 8))  # msg_1 once, plus the id-less line
        self.assertEqual(s["tools"]["Bash"], 1)

    def test_glob_characters_in_a_session_id_match_nothing(self):
        self.transcript("s1", [("2026-11-20T10:00:00Z", 1, 0, 1), ("2026-11-20T10:10:00Z", 1, 0, 1)])
        self.run_json("t1", {"ticket": "t1", "sessions": ["*", "s?", "../x", "s[1]"]})
        out = self.report()
        self.assertIn("sessions: 0 of 4 with a transcript", out)
        self.assertNotIn("tokens:", out)

    def test_no_run_json(self):
        self.assertIn("no run.json at", self.report("nope"))

    def test_cli_ticket_and_positional_days_still_work(self):
        self.run_json("t1", {"ticket": "t1", "sessions": []})
        script = os.path.join(ROOT, "adapters", "claude", "usage_report.py")
        env = dict(os.environ, AI_SETUP_PROJECTS_DIR=self.projects)
        run = subprocess.run([sys.executable, "-I", script, "--ticket", "t1", "--dev-root", self.dev],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Ticket t1", run.stdout)
        days = subprocess.run([sys.executable, "-I", script, "30"], capture_output=True, text=True,
                              env=dict(env, HOME=self.dev, AI_SETUP_GUARD_LOG="off", AI_SETUP_ACTIONS_LOG=os.path.join(self.dev, "a.log")))
        self.assertEqual(days.returncode, 0, days.stderr)
        self.assertIn("Sessions:", days.stdout)


if __name__ == "__main__":
    unittest.main()
