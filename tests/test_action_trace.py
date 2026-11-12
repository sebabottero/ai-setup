"""action_trace: generic PreToolUse hook driven by a policy `trace` rule.
No rules means no-op. Never blocks."""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "action_trace.py")
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude", "hooks"))
import action_trace

# The rule a layer would write for "cloudcp changes on REMOTE:". Matched over the program and its non-flag words, so
# flags between the subcommand and the path do not matter. An allowlist of changing subcommands, no denylist.
R = "REMOTE:"
RULE = {"match": [f"cloudcp {sub} * {R}*" for sub in ("copy", "copyto", "sync")]
        + [g for sub in ("move", "moveto", "bisync", "delete", "deletefile", "purge", "rmdir", "rmdirs", "mkdir", "touch", "cleanup")
           for g in (f"cloudcp {sub} {R}*", f"cloudcp {sub} * {R}*")],
        "log": "{{DEV}}/logs/trace.log",
        "high_risk": {"sync": ["cloudcp sync *"], "purge": ["cloudcp purge *"],
                      "--no-trash=false": ["* --no-trash=false", "* --no-trash=false *",
                                           "* --no-trash false", "* --no-trash false *"]}}


def subs(command, rules=(RULE,)):
    return [(c["sub"], c["risks"]) for c in action_trace.changes(command, list(rules))]


class Detection(unittest.TestCase):
    def test_matching_commands_are_found(self):
        self.assertEqual(subs("cloudcp mkdir REMOTE:zz-test"), [("mkdir", [])])
        self.assertEqual(subs("/usr/local/bin/cloudcp copy ./out REMOTE:posts --progress"), [("copy", [])])
        self.assertEqual(subs("cd x && cloudcp rmdir REMOTE:zz-test"), [("rmdir", [])])

    def test_read_only_and_unrelated_commands_are_not(self):
        for cmd in ("cloudcp lsd REMOTE:", "cloudcp ls REMOTE:x", "cloudcp lsf REMOTE:", "cloudcp about REMOTE:",
                    "cloudcp check a REMOTE:b", "cloudcp copy REMOTE:a /tmp/local", "cloudcp mkdir other:x",
                    "echo cloudcp mkdir REMOTE:x", "ls REMOTE:"):
            self.assertEqual(subs(cmd), [], cmd)

    def test_high_risk(self):
        self.assertEqual(subs("cloudcp sync ./a REMOTE:b"), [("sync", ["sync"])])
        self.assertEqual(subs("cloudcp purge REMOTE:old"), [("purge", ["purge"])])
        self.assertEqual(subs("cloudcp copy a REMOTE:b --no-trash=false"), [("copy", ["--no-trash=false"])])
        self.assertEqual(subs("cloudcp delete REMOTE:x --no-trash=false"), [("delete", ["--no-trash=false"])])
        self.assertEqual(subs("cloudcp delete REMOTE:x --no-trash false"), [("delete", ["--no-trash=false"])])
        self.assertEqual(subs("cloudcp copy sync REMOTE:b"), [("copy", [])])  # a local path named sync is not `sync`
        self.assertEqual(subs("cloudcp -v sync a REMOTE:b"), [("sync", ["sync"])])
        self.assertIn("HIGH RISK", action_trace.warning(action_trace.changes("cloudcp purge REMOTE:old", [RULE])))
        self.assertIsNone(action_trace.warning(action_trace.changes("cloudcp copy a REMOTE:b", [RULE])))

    def test_reads_and_flags(self):
        for cmd in ("cloudcp lsjson REMOTE:", "cloudcp cat REMOTE:a", "cloudcp size REMOTE:", "cloudcp tree REMOTE:",
                    "cloudcp md5sum REMOTE:", "cloudcp lsl REMOTE:", "cloudcp link REMOTE:a", "cloudcp config show REMOTE:",
                    "cloudcp copy --progress REMOTE:a /tmp/x", "cloudcp -v ls REMOTE:"):
            self.assertEqual(subs(cmd), [], cmd)
        self.assertEqual(subs("cloudcp copy REMOTE:a REMOTE:b"), [("copy", [])])  # the destination is the remote
        self.assertEqual(subs("cloudcp copy --progress ./a REMOTE:b"), [("copy", [])])
        self.assertEqual(subs("cloudcp -v mkdir REMOTE:x"), [("mkdir", [])])

    def test_flag_values_and_extra_words(self):
        self.assertEqual(subs("cloudcp copy ./a REMOTE:b --exclude x"), [("copy", [])])
        self.assertEqual(subs("cloudcp copy a REMOTE:b c"), [("copy", [])])
        # a download whose flag takes a separate value is over-logged: globs cannot tell a flag value from a path
        self.assertEqual(subs("cloudcp copy --transfers 4 REMOTE:a /tmp/x"), [("copy", [])])

    def test_dry_run_is_marked(self):
        self.assertTrue(action_trace.changes("cloudcp copy a REMOTE:b --dry-run", [RULE])[0]["dry"])
        self.assertTrue(action_trace.changes("cloudcp copy a REMOTE:b -n", [RULE])[0]["dry"])
        self.assertFalse(action_trace.changes("cloudcp copy a REMOTE:b", [RULE])[0]["dry"])

    def test_no_rules_is_a_no_op(self):
        self.assertEqual(action_trace.changes("cloudcp purge REMOTE:old", []), [])
        self.assertEqual(action_trace.rules({}), [])
        self.assertEqual(action_trace.rules({"trace": "junk"}), [])


class Hook(unittest.TestCase):
    def run_hook(self, command, tool="Bash", policy="rule"):
        base = tempfile.mkdtemp()
        pol = os.path.join(base, "policy.json")
        with open(pol, "w") as f:
            json.dump({"dev_root": base, "trace": [RULE]} if policy == "rule" else {}, f)
        env = dict(os.environ, AI_SETUP_POLICY=pol)
        event = json.dumps({"tool_name": tool, "session_id": "s1", "tool_input": {"command": command}})
        proc = subprocess.run([sys.executable, "-I", HOOK], input=event, capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        log = os.path.join(base, "logs", "trace.log")
        lines = open(log).read().splitlines() if os.path.exists(log) else []
        return proc.stdout, lines

    def test_mutation_is_logged_with_fields(self):
        out, lines = self.run_hook("cloudcp copy ./a REMOTE:b")
        self.assertIn("logged: cloudcp copy ./a REMOTE:b", out)
        self.assertNotIn("HIGH RISK", out)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split("\t")[1:], ["s1", "copy", "./a", "REMOTE:b", "-", "-"])

    def test_read_only_is_not_logged(self):
        self.assertEqual(self.run_hook("cloudcp lsd REMOTE:"), ("", []))

    def test_high_risk_warns_and_marks_the_line(self):
        out, lines = self.run_hook("cloudcp sync ./a REMOTE:b")
        self.assertIn("HIGH RISK", out)
        self.assertIn("HIGH-RISK:sync", lines[0])

    def test_dry_run_is_marked_in_the_line(self):
        _, lines = self.run_hook("cloudcp copy ./a REMOTE:b --dry-run")
        self.assertEqual(lines[0].split("\t")[-1], "dry-run")

    def test_other_tools_are_ignored(self):
        self.assertEqual(self.run_hook("cloudcp mkdir REMOTE:x", tool="Edit"), ("", []))

    def test_no_rules_does_nothing(self):
        self.assertEqual(self.run_hook("cloudcp purge REMOTE:x", policy="none"), ("", []))


if __name__ == "__main__":
    unittest.main()
