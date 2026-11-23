"""Criterion 4: how a guard ask ended is recorded in actions.log (approved / declined; unknown for OpenCode).
Criterion 5: core/guard/run_json.py keeps handoffs/<ticket>/run.json, and ticket-flow calls it (wording check)."""
import json, os, re, subprocess, sys, tempfile, unittest, unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "ask_outcome.py")
GUARD_HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "policy_guard.py")
GUARD = os.path.join(ROOT, "core", "guard", "guard.py")
RUN_JSON = os.path.join(ROOT, "core", "guard", "run_json.py")
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))


class AskOutcome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.log = os.path.join(self.tmp, "actions.log")
        self.env = dict(os.environ, AI_SETUP_ACTIONS_LOG=self.log, AI_SETUP_GUARD_LOG="off",
                        AI_SETUP_PENDING_DIR=os.path.join(self.tmp, "pending"))

    def run_py(self, script, payload, env=None):
        out = subprocess.run([sys.executable, "-I", script], input=json.dumps(payload), capture_output=True, text=True,
                             env=env or self.env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def ask(self, tool_use_id="t1", session="s1", command="git push origin main"):
        out = self.run_py(GUARD_HOOK, {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ROOT,
                                       "session_id": session, "tool_use_id": tool_use_id})
        self.assertIn('"ask"', out)

    def post(self, kind, session="s1", **extra):
        self.run_py(HOOK, dict({"hook_event_name": kind, "session_id": session}, **extra))

    def lines(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [l.rstrip("\n").split("\t") for l in f]

    def whats(self):
        return [(l[1], l[3], l[5]) for l in self.lines()]

    def test_an_ask_that_ran_is_approved_and_linked_by_session_and_command(self):
        self.ask()
        self.post("PostToolUse", tool_use_id="t1")
        self.assertEqual(self.whats(), [("s1", "asked", "git push origin main"), ("s1", "approved", "git push origin main")])
        self.assertEqual(self.lines()[0][2], self.lines()[1][2])  # same risk
        self.post("SessionEnd")  # the marker is gone: nothing is declined afterwards
        self.assertEqual(len(self.lines()), 2)

    def test_a_failed_run_is_approved_but_a_refused_one_is_not(self):
        self.ask("t1"), self.ask("t2", command="git push origin dev"), self.ask("t3", command="git push origin x")
        self.post("PostToolUseFailure", tool_use_id="t1", error="exit code 1", is_interrupt=False)
        self.post("PostToolUseFailure", tool_use_id="t2", error="The user doesn't want to proceed with this tool use. The tool use was rejected", is_interrupt=False)
        self.post("PostToolUseFailure", tool_use_id="t3", error="x", is_interrupt=True)
        self.assertEqual([w for _, w, _ in self.whats() if w != "asked"], ["approved"])

    def test_shell_permission_denied_is_approved_the_harness_refusal_is_not(self):
        for tid, error in (("a", "Exit code 126\nbash: ./deploy.sh: Permission denied"), ("b", "Permission for this tool use was denied."),
                           ("c", "Permission to use Bash with command git push has been denied."), ("d", "Exit code 1\nThe user doesn't want to proceed")):
            self.ask(tid, command=f"git push origin {tid}")
            self.post("PostToolUseFailure", tool_use_id=tid, error=error, is_interrupt=False)
        self.assertEqual([w[2][-1] for w in self.whats() if w[1] == "approved"], ["a", "d"])

    def test_session_start_remembers_the_session_for_run_json_auto(self):
        sessions = os.path.join(self.tmp, "sessions")
        env = dict(self.env, AI_SETUP_SESSIONS_DIR=sessions)
        folder = os.path.realpath(tempfile.mkdtemp())
        self.run_py(HOOK, {"hook_event_name": "SessionStart", "session_id": "sess-9", "cwd": folder}, env=env)
        dev = tempfile.mkdtemp()
        def run(cwd):
            return subprocess.run([sys.executable, "-I", RUN_JSON, "update", "T-1", "--dev-root", dev, "--session", "auto"],
                                  capture_output=True, text=True, cwd=cwd, env=env, timeout=30)
        self.assertEqual(run(folder).returncode, 0)
        with open(os.path.join(dev, "handoffs", "T-1", "run.json")) as f:
            self.assertEqual(json.load(f)["sessions"], ["sess-9"])
        other = run(tempfile.mkdtemp())  # another folder: nothing stored, a note, no session added
        self.assertEqual(other.returncode, 0)
        self.assertIn("no session id", other.stderr)
        with open(os.path.join(dev, "handoffs", "T-1", "run.json")) as f:
            self.assertEqual(json.load(f)["sessions"], ["sess-9"])

    def test_an_ask_left_at_session_end_is_declined(self):
        self.ask("t1"), self.ask("t2", session="s2", command="git push origin dev")
        self.post("SessionEnd", session="s1")
        self.assertEqual([w for w in self.whats() if w[1] == "declined"], [("s1", "declined", "git push origin main")])
        self.post("SessionEnd", session="s1")  # idempotent
        self.assertEqual(len([w for w in self.whats() if w[1] == "declined"]), 1)

    def test_start_sweeps_only_old_markers_of_other_sessions(self):
        import outcomes
        os.environ.update(AI_SETUP_ACTIONS_LOG=self.log, AI_SETUP_PENDING_DIR=self.env["AI_SETUP_PENDING_DIR"])
        self.addCleanup(lambda: [os.environ.pop(k) for k in ("AI_SETUP_ACTIONS_LOG", "AI_SETUP_PENDING_DIR")])
        outcomes.write_marker("old", "dead", "high", "git-push", "git push")
        outcomes.write_marker("mine", "s1", "high", "git-push", "git push mine")
        outcomes.write_marker("recent", "other", "high", "git-push", "git push other")
        outcomes.sweep("s1", now=__import__("time").time() + outcomes.STALE - 60)  # only markers older than STALE
        self.assertEqual(self.lines(), [])
        outcomes.sweep("s1", now=__import__("time").time() + outcomes.STALE + 60)
        self.assertEqual(sorted(w[0] for w in self.whats()), ["dead", "other"])  # "mine" belongs to the live session

    def test_allowed_and_denied_commands_leave_no_marker(self):
        self.run_py(GUARD_HOOK, {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": ROOT,
                                 "session_id": "s1", "tool_use_id": "t9"})
        self.assertFalse(os.path.exists(self.env["AI_SETUP_PENDING_DIR"]) and os.listdir(self.env["AI_SETUP_PENDING_DIR"]))

    def test_opencode_asks_say_unknown(self):
        out = self.run_py(GUARD, {"tool": "bash", "command": "git push origin main"})
        self.assertEqual(json.loads(out)["decision"], "ask")
        self.assertEqual([w for _, w, _ in self.whats()], ["asked", "unknown"])

    def test_the_hooks_fail_open(self):
        blocker = os.path.join(self.tmp, "a-file")
        open(blocker, "w").close()
        broken = dict(self.env, AI_SETUP_PENDING_DIR=os.path.join(blocker, "pending"))  # cannot be created: its parent is a file
        for env in (self.env, broken):
            for raw in ("not json", "", "[1]"):
                out = subprocess.run([sys.executable, "-I", HOOK], input=raw, capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual((out.returncode, out.stdout), (0, ""), (raw, out.stderr))
            for kind in ("PostToolUse", "SessionEnd", "SessionStart"):
                self.run_py(HOOK, {"hook_event_name": kind, "session_id": "s1", "tool_use_id": "t1"}, env=env)
        # the guard's answer is the same with a pending dir it cannot write
        payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": ROOT,
                   "session_id": "s1", "tool_use_id": "t1"}
        good = self.run_py(GUARD_HOOK, payload)
        self.assertEqual(self.run_py(GUARD_HOOK, payload, env=broken), good)
        self.assertIn('"ask"', good)

    def test_the_hook_is_registered_for_the_four_events(self):
        text = open(os.path.join(ROOT, "install.py")).read()
        for event in ("PostToolUse", "PostToolUseFailure", "SessionEnd", "SessionStart"):
            self.assertIn(f'"{event}"', text)
        self.assertIn("ask_outcome.py", text)


class RunJson(unittest.TestCase):
    def setUp(self):
        self.dev = tempfile.mkdtemp()
        self.path = os.path.join(self.dev, "handoffs", "T-1", "run.json")

    def call(self, *args):
        out = subprocess.run([sys.executable, "-I", RUN_JSON, "update", "T-1", "--dev-root", self.dev, *args],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), self.path)
        with open(self.path) as f:
            return json.load(f)

    def test_created_at_the_first_gate_and_extended_at_the_next(self):
        run = self.call("--session", "s1", "--branch", "ai/t-1")
        self.assertEqual((run["sessions"], run["branch"], run["pr"], run["end"]), (["s1"], "ai/t-1", None, None))
        self.assertTrue(re.match(r"\d{4}-\d\d-\d\dT", run["start"]))
        start = run["start"]
        self.call("--session", "s1", "--round", "3:FAIL:/r/x.md")
        self.call("--session", "s2", "--round", "3:PASS:/r/x.md", "--round", "4:PASS")
        run = self.call("--pr", "12", "--end")
        self.assertEqual(run["sessions"], ["s1", "s2"])
        self.assertEqual([(r["stage"], r["n"], r["verdict"]) for r in run["rounds"]], [(3, 1, "FAIL"), (3, 2, "PASS"), (4, 1, "PASS")])
        self.assertEqual(run["reports"], ["/r/x.md"])
        self.assertEqual((run["start"], run["pr"], bool(run["end"]), run["branch"]), (start, 12, True, "ai/t-1"))

    def test_a_ticket_slug_cannot_leave_the_handoffs_folder(self):
        for slug in ("../x", "a/b", "..", ".", "", ".hidden", "a\\b"):
            out = subprocess.run([sys.executable, "-I", RUN_JSON, "update", slug, "--dev-root", self.dev],
                                 capture_output=True, text=True, timeout=30)
            self.assertNotEqual(out.returncode, 0, slug)
            self.assertIn("ticket", out.stderr, slug)
        self.assertEqual(os.listdir(self.dev), [])

    def test_an_unreadable_dev_root_is_an_error_not_home(self):
        import guard, run_json
        with unittest.mock.patch.object(guard, "load", side_effect=OSError("no policy")), \
                unittest.mock.patch.object(run_json, "update") as update:
            with self.assertRaises(SystemExit) as stop:
                run_json.main(["update", "T-1"])
        self.assertNotEqual(stop.exception.code, 0)
        update.assert_not_called()

    def test_a_bad_round_is_refused(self):
        out = subprocess.run([sys.executable, "-I", RUN_JSON, "update", "T-1", "--dev-root", self.dev, "--round", "PASS"],
                             capture_output=True, text=True, timeout=30)
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse(os.path.exists(self.path))

    def test_ticket_flow_writes_it_at_0a_and_at_each_gate(self):
        with open(os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md"), encoding="utf-8") as f:
            text = re.sub(r"\s+", " ", f.read())
        for needle in ("core/guard/run_json.py update", "handoffs/<ticket>/run.json", "0a after my OK",
                       "Gate 1 after my OK", "--round 3:<verdict>", "--pr N", "--end", "nothing resumes from it"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
