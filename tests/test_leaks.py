"""Leak check: the public repo carries no personal terms and no Drive trace specifics. Personal bits live in layers."""
import os, re, subprocess, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIS = os.path.relpath(os.path.abspath(__file__), ROOT)
# Author name and handle contain a banned term; they are stripped before scanning.
ALLOWED_TOKENS = re.compile(r"sebabottero|Seba Bottero", re.I)
TERMS = re.compile(r"botter|instagram|GDrive|Orca|mercury|adhd", re.I)
# Files allowed to hold personal terms: none today. Add a path here only with a reason in the PR.
PATH_ALLOWLIST = frozenset()
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".pyc", ".zip")


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        names = [n for n in out.decode().split("\0") if n]
        if names:
            return [n for n in names if os.path.isfile(os.path.join(ROOT, n))]
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found += [os.path.relpath(os.path.join(base, f), ROOT) for f in files]
    return found


def read(name):
    if name.lower().endswith(BINARY):
        return ""
    with open(os.path.join(ROOT, name), encoding="utf-8", errors="ignore") as f:
        return f.read()


class Leaks(unittest.TestCase):
    def test_no_personal_terms(self):
        files = [n for n in tracked_files() if n != THIS and n not in PATH_ALLOWLIST]
        self.assertGreater(len(files), 20)
        hits = []
        for name in files:
            for i, line in enumerate(ALLOWED_TOKENS.sub("", read(name)).splitlines(), 1):
                if TERMS.search(line):
                    hits.append(f"{name}:{i}: {line.strip()[:100]}")
        self.assertEqual(hits, [], "personal terms in the public repo:\n" + "\n".join(hits))

    def test_no_drive_trace_in_public_code(self):
        bad = re.compile(r"rclone|drive-changes", re.I)
        files = [n for n in tracked_files() if n != THIS and (
            n.endswith((".py", ".sh")) and not n.startswith("tests/")
            or n.endswith((".js", ".md")) and n.startswith(("core/", "adapters/"))
            or n in ("core/AGENTS.md", ".claude/settings.json"))]
        self.assertIn("core/AGENTS.md", files)
        hits = [n for n in files if bad.search(read(n))]
        self.assertEqual(hits, [], "Drive trace specifics in public code")


if __name__ == "__main__":
    unittest.main()
