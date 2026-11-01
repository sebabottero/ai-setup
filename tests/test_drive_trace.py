import os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "drive_trace.py")
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude", "hooks"))
import drive_trace


def subs(command):
    return [(c["sub"], c["risks"]) for c in drive_trace.changes(command)]


class Detection(unittest.TestCase):
    def test_mutating_commands_on_the_drive_remote_are_found(self):
        self.assertEqual(subs("rclone mkdir GDrive:zz-test"), [("mkdir", [])])
        self.assertEqual(subs("/opt/homebrew/bin/rclone copy ./out GDrive:posts --progress"), [("copy", [])])
        self.assertEqual(subs("cd x && rclone rmdir GDrive:zz-test"), [("rmdir", [])])
        self.assertEqual(subs("rclone move GDrive:a ./local"), [("move", [])])  # move deletes at the source

    def test_read_only_and_unrelated_commands_are_not(self):
        for cmd in ("rclone lsd GDrive:", "rclone ls GDrive:x", "rclone lsf GDrive:", "rclone about GDrive:",
                    "rclone check a GDrive:b", "rclone copy GDrive:a ./local", "rclone mkdir other:x",
                    "echo rclone mkdir GDrive:x", "ls GDrive:"):
            self.assertEqual(subs(cmd), [], cmd)

    def test_high_risk(self):
        self.assertEqual(subs("rclone sync ./a GDrive:b"), [("sync", ["sync"])])
        self.assertEqual(subs("rclone purge GDrive:old"), [("purge", ["purge"])])
        self.assertEqual(subs("rclone delete GDrive:x --drive-use-trash=false"), [("delete", ["--drive-use-trash=false"])])
        self.assertEqual(subs("rclone delete GDrive:x --drive-use-trash false"), [("delete", ["--drive-use-trash=false"])])
        self.assertIn("HIGH RISK", drive_trace.warning(drive_trace.changes("rclone purge GDrive:old")))
        self.assertIsNone(drive_trace.warning(drive_trace.changes("rclone copy a GDrive:b")))


class Hook(unittest.TestCase):
    def run_hook(self, command, tool="Bash"):
        log = os.path.join(tempfile.mkdtemp(), "sub", "drive.log")
        env = dict(os.environ, AI_SETUP_DRIVE_LOG=log)
        event = '{"tool_name": "%s", "session_id": "s1", "tool_input": {"command": "%s"}}' % (tool, command)
        out = subprocess.run([sys.executable, "-I", HOOK], input=event, capture_output=True, text=True, env=env).stdout
        lines = []
        if os.path.exists(log):
            with open(log) as f:
                lines = f.read().splitlines()
        return out, lines

    def test_mutation_is_logged_with_fields(self):
        out, lines = self.run_hook("rclone copy ./a GDrive:b")
        self.assertIn("Drive change logged: rclone copy ./a GDrive:b", out)
        self.assertNotIn("HIGH RISK", out)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split("\t")[1:], ["s1", "copy", "./a", "GDrive:b", "-", "-"])

    def test_read_only_is_not_logged(self):
        self.assertEqual(self.run_hook("rclone lsd GDrive:"), ("", []))

    def test_high_risk_warns_and_marks_the_line(self):
        out, lines = self.run_hook("rclone sync ./a GDrive:b")
        self.assertIn("HIGH RISK", out)
        self.assertIn("HIGH-RISK:sync", lines[0])

    def test_other_tools_are_ignored(self):
        self.assertEqual(self.run_hook("rclone mkdir GDrive:x", tool="Edit"), ("", []))


if __name__ == "__main__":
    unittest.main()
