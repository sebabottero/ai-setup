"""The work root is {{DEV}} (from a layer's dev_root, default ~): no literal ~/Dev in core rules, guard or skills."""
import os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import guard

LITERAL = re.compile(r"~/Dev\b")


def files():
    yield os.path.join(ROOT, "core", "AGENTS.md")
    yield os.path.join(ROOT, "core", "policy.json")
    for top in ("guard", "skills"):
        for dirpath, dirs, names in os.walk(os.path.join(ROOT, "core", top)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in names:
                if n.endswith((".py", ".md", ".json", ".sh")):
                    yield os.path.join(dirpath, n)


class NoLiteralDev(unittest.TestCase):
    def test_core_has_no_literal_dev_folder(self):
        hits = []
        for p in files():
            with open(p) as f:
                hits += [f"{os.path.relpath(p, ROOT)}:{i}" for i, line in enumerate(f, 1) if LITERAL.search(line)]
        self.assertEqual(hits, [])


class Defaults(unittest.TestCase):
    def test_actions_log_follows_dev_root(self):
        old = os.environ.pop("AI_SETUP_ACTIONS_LOG", None)
        self.addCleanup(lambda: old is None or os.environ.__setitem__("AI_SETUP_ACTIONS_LOG", old))
        self.assertEqual(guard.actions_log_path({"dev_root": "~/work"}), os.path.expanduser("~/work/logs/actions.log"))
        self.assertEqual(guard.actions_log_path({}), os.path.expanduser("~/logs/actions.log"))

    def test_audit_dev_root_default_follows_the_layer(self):
        audit = os.path.join(ROOT, "core", "skills", "ai-audit", "audit.py")
        with tempfile.TemporaryDirectory() as d:
            pol = os.path.join(d, "policy.json")
            with open(pol, "w") as f:
                f.write('{"dev_root": "%s"}' % d)
            code = ("import sys, os; sys.argv=['a']; sys.path.insert(0, %r); import audit; "
                    "print(audit.default_dev_root())" % os.path.dirname(audit))
            env = {k: v for k, v in os.environ.items() if k != "AI_AUDIT_DEV_ROOT"}
            env["AI_SETUP_POLICY"] = pol
            out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, env=env).stdout.strip()
            self.assertEqual(out, d)


if __name__ == "__main__":
    unittest.main()
