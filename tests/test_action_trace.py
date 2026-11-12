"""action_trace: generic PreToolUse hook driven by a policy `trace` rule. Cases ported from test_drive_trace.py.
No rules means no-op. Never blocks."""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "action_trace.py")
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude", "hooks"))
import action_trace

# The rule a layer would write for "rclone changes on GDrive:". Matched over the program and its non-flag words, so
# flags between the subcommand and the path do not matter. An allowlist of changing subcommands, no denylist.
R = "GDrive:"
RULE = {"match": [f"rclone {sub} * {R}*" for sub in ("copy", "copyto", "sync")]
        + [g for sub in ("move", "moveto", "bisync", "delete", "deletefile", "purge", "rmdir", "rmdirs", "mkdir", "touch", "cleanup")
           for g in (f"rclone {sub} {R}*", f"rclone {sub} * {R}*")],
        "log": "{{DEV}}/logs/drive.log",
        "high_risk": {"sync": ["rclone sync *"], "purge": ["rclone purge *"],
                      "--drive-use-trash=false": ["* --drive-use-trash=false", "* --drive-use-trash=false *",
                                                  "* --drive-use-trash false", "* --drive-use-trash false *"]}}


def subs(command, rules=(RULE,)):
    return [(c["sub"], c["risks"]) for c in action_trace.changes(command, list(rules))]


class Detection(unittest.TestCase):
    def test_matching_commands_are_found(self):
        self.assertEqual(subs("rclone mkdir GDrive:zz-test"), [("mkdir", [])])
        self.assertEqual(subs("/opt/homebrew/bin/rclone copy ./out GDrive:posts --progress"), [("copy", [])])
        self.assertEqual(subs("cd x && rclone rmdir GDrive:zz-test"), [("rmdir", [])])

    def test_read_only_and_unrelated_commands_are_not(self):
        for cmd in ("rclone lsd GDrive:", "rclone ls GDrive:x", "rclone lsf GDrive:", "rclone about GDrive:",
                    "rclone check a GDrive:b", "rclone copy GDrive:a /tmp/local", "rclone mkdir other:x",
                    "echo rclone mkdir GDrive:x", "ls GDrive:"):
            self.assertEqual(subs(cmd), [], cmd)

    def test_high_risk(self):
        self.assertEqual(subs("rclone sync ./a GDrive:b"), [("sync", ["sync"])])
        self.assertEqual(subs("rclone purge GDrive:old"), [("purge", ["purge"])])
        self.assertEqual(subs("rclone copy a GDrive:b --drive-use-trash=false"), [("copy", ["--drive-use-trash=false"])])
        self.assertEqual(subs("rclone delete GDrive:x --drive-use-trash=false"), [("delete", ["--drive-use-trash=false"])])
        self.assertEqual(subs("rclone delete GDrive:x --drive-use-trash false"), [("delete", ["--drive-use-trash=false"])])
        self.assertEqual(subs("rclone copy sync GDrive:b"), [("copy", [])])  # a local path named sync is not `sync`
        self.assertEqual(subs("rclone -v sync a GDrive:b"), [("sync", ["sync"])])
        self.assertIn("HIGH RISK", action_trace.warning(action_trace.changes("rclone purge GDrive:old", [RULE])))
        self.assertIsNone(action_trace.warning(action_trace.changes("rclone copy a GDrive:b", [RULE])))

    def test_reads_and_flags(self):
        for cmd in ("rclone lsjson GDrive:", "rclone cat GDrive:a", "rclone size GDrive:", "rclone tree GDrive:",
                    "rclone md5sum GDrive:", "rclone lsl GDrive:", "rclone link GDrive:a", "rclone config show GDrive:",
                    "rclone copy --progress GDrive:a /tmp/x", "rclone -v ls GDrive:"):
            self.assertEqual(subs(cmd), [], cmd)
        self.assertEqual(subs("rclone copy GDrive:a GDrive:b"), [("copy", [])])  # the destination is Drive
        self.assertEqual(subs("rclone copy --progress ./a GDrive:b"), [("copy", [])])
        self.assertEqual(subs("rclone -v mkdir GDrive:x"), [("mkdir", [])])

    def test_dry_run_is_marked(self):
        self.assertTrue(action_trace.changes("rclone copy a GDrive:b --dry-run", [RULE])[0]["dry"])
        self.assertTrue(action_trace.changes("rclone copy a GDrive:b -n", [RULE])[0]["dry"])
        self.assertFalse(action_trace.changes("rclone copy a GDrive:b", [RULE])[0]["dry"])

    def test_no_rules_is_a_no_op(self):
        self.assertEqual(action_trace.changes("rclone purge GDrive:old", []), [])
        self.assertEqual(action_trace.rules({}), [])
        self.assertEqual(action_trace.rules({"trace": "junk"}), [])


PARITY = [
    "rclone mkdir GDrive:zz-test", "/opt/homebrew/bin/rclone copy ./out GDrive:posts --progress", "cd x && rclone rmdir GDrive:zz-test",
    "rclone move GDrive:a ./local", "rclone move ./a GDrive:b", "rclone moveto ./a GDrive:b", "rclone bisync ./a GDrive:b",
    "rclone lsd GDrive:", "rclone ls GDrive:x", "rclone lsf GDrive:", "rclone about GDrive:", "rclone check a GDrive:b",
    "rclone lsjson GDrive:", "rclone cat GDrive:a", "rclone size GDrive:", "rclone tree GDrive:", "rclone md5sum GDrive:",
    "rclone lsl GDrive:", "rclone link GDrive:a", "rclone config show GDrive:", "rclone copy GDrive:a ./local",
    "rclone copy GDrive:a GDrive:b", "rclone copy --progress GDrive:a /tmp/x", "rclone -v ls GDrive:", "rclone -v mkdir GDrive:x",
    "rclone mkdir other:x", "echo rclone mkdir GDrive:x", "ls GDrive:", "rclone sync ./a GDrive:b", "rclone sync GDrive:a ./b",
    "rclone purge GDrive:old", "rclone copy sync GDrive:b", "rclone -v sync a GDrive:b",
    "rclone delete GDrive:x --drive-use-trash=false", "rclone delete GDrive:x --drive-use-trash false",
    "rclone copy a GDrive:b --drive-use-trash=false", "rclone copy a GDrive:b --dry-run", "rclone copy a GDrive:b -n",
    "rclone deletefile GDrive:x/y", "rclone rmdirs GDrive:x", "rclone touch GDrive:x", "rclone cleanup GDrive:",
    "rclone copyto ./a GDrive:b/c", "rclone mkdir GDrive:a && rclone purge GDrive:b",
]


class Parity(unittest.TestCase):
    def test_same_results_as_drive_trace(self):
        import drive_trace
        keys = ("sub", "src", "dst", "risks", "dry")
        self.assertGreaterEqual(len(PARITY), 20)
        for cmd in PARITY:
            old = [{k: c[k] for k in keys} for c in drive_trace.changes(cmd)]
            new = [{k: c[k] for k in keys} for c in action_trace.changes(cmd, [RULE])]
            self.assertEqual(new, old, cmd)


# Intentional differences from drive_trace, whose positional-only parsing misses real changes or cannot tell a flag value
# from a path. The new hook is the one to trust; PARITY above leaves these out.
KNOWN_DIFFERENCES = [
    # (command, drive_trace logs it, action_trace logs it)
    ("rclone copy ./a GDrive:b --exclude x", False, True),  # flag value "x" hides the destination from drive_trace
    ("rclone copy a GDrive:b c", False, True),  # drive_trace only looks at the last word
    ("rclone copy --transfers 4 GDrive:a /tmp/x", False, True),  # a download, but the flag value "4" shifts the words: over-logged
]


class KnownDifferences(unittest.TestCase):
    def test_documented_differences(self):
        import drive_trace
        for cmd, old, new in KNOWN_DIFFERENCES:
            self.assertEqual(bool(drive_trace.changes(cmd)), old, cmd)
            self.assertEqual(bool(action_trace.changes(cmd, [RULE])), new, cmd)


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
        log = os.path.join(base, "logs", "drive.log")
        lines = open(log).read().splitlines() if os.path.exists(log) else []
        return proc.stdout, lines

    def test_mutation_is_logged_with_fields(self):
        out, lines = self.run_hook("rclone copy ./a GDrive:b")
        self.assertIn("logged: rclone copy ./a GDrive:b", out)
        self.assertNotIn("HIGH RISK", out)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split("\t")[1:], ["s1", "copy", "./a", "GDrive:b", "-", "-"])

    def test_read_only_is_not_logged(self):
        self.assertEqual(self.run_hook("rclone lsd GDrive:"), ("", []))

    def test_high_risk_warns_and_marks_the_line(self):
        out, lines = self.run_hook("rclone sync ./a GDrive:b")
        self.assertIn("HIGH RISK", out)
        self.assertIn("HIGH-RISK:sync", lines[0])

    def test_dry_run_is_marked_in_the_line(self):
        _, lines = self.run_hook("rclone copy ./a GDrive:b --dry-run")
        self.assertEqual(lines[0].split("\t")[-1], "dry-run")

    def test_other_tools_are_ignored(self):
        self.assertEqual(self.run_hook("rclone mkdir GDrive:x", tool="Edit"), ("", []))

    def test_no_rules_does_nothing(self):
        self.assertEqual(self.run_hook("rclone purge GDrive:x", policy="none"), ("", []))


if __name__ == "__main__":
    unittest.main()
