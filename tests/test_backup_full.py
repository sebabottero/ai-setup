"""backup.sh --full / --restore: allowlist only, secrets never copied, round-trip, no overwrite. A fake `age` stands in for the real one."""
import json
import os
import subprocess
import tarfile
import tempfile
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import backup_full
FAKE_AGE = """#!/bin/sh
# -p -o OUT IN  /  -d -o OUT IN
mode=$1; out=$3; in=$4
if [ "$mode" = "-p" ]; then { printf 'age-encryption.org/v1\\n'; cat "$in"; } > "$out"; else tail -n +2 "$in" > "$out"; fi
"""


def write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class BackupFull(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = self._t.name
        self.home = os.path.join(t, "home")
        self.dest = os.path.join(t, "disk")
        self.bin = os.path.join(t, "bin")
        write(os.path.join(self.bin, "age"), FAKE_AGE)
        os.chmod(os.path.join(self.bin, "age"), 0o755)
        h = self.home
        write(f"{h}/.gitconfig", "[user]")
        write(f"{h}/Dev/handoffs/a.md", "handoff")
        write(f"{h}/Dev/side-project/brand.md", "brand")
        write(f"{h}/Dev/side-project/models/big.bin", "model")
        write(f"{h}/Dev/side-project/exports/big.mp4", "export")
        write(f"{h}/.claude/projects/p1/memory/m.md", "memory")
        write(f"{h}/.claude/projects/p1/session.jsonl", "transcript")
        write(f"{h}/.ssh/id_ed25519", "SECRET")
        write(f"{h}/.config/gh/hosts.yml", "SECRET")
        write(f"{h}/.claude.json", "SECRET")
        policy = os.path.join(t, "policy.json")  # a fake layer: its folders to include and exclude
        with open(policy, "w") as f:
            json.dump({"dev_root": "~/Dev", "backup": {"include": ["{{DEV}}/side-project"],
                       "exclude": ["{{DEV}}/side-project/models", "{{DEV}}/side-project/exports"]}}, f)
        self.env = {**os.environ, "HOME": h, "PATH": f"{self.bin}:/usr/bin:/bin", "AI_SETUP_POLICY": policy}

    def tearDown(self):
        self._t.cleanup()

    def run_sh(self, *args, path=None):
        env = dict(self.env)
        if path:
            env["PATH"] = path
        return subprocess.run([os.path.join(ROOT, "backup.sh"), *args], capture_output=True, text=True, env=env)

    def make(self):
        r = self.run_sh("--full", self.dest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return os.path.join(self.dest, [n for n in os.listdir(self.dest) if n.endswith(".age")][0]), r

    def names(self, age_file):
        plain = age_file + ".tar"
        subprocess.run(f"tail -n +2 '{age_file}' > '{plain}'", shell=True, check=True)
        with tarfile.open(plain) as tar:
            return tar.getnames()

    def test_dry_run_lists_and_writes_nothing(self):
        r = self.run_sh("--full", self.dest, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("IN (", r.stdout)
        self.assertIn("NOT IN", r.stdout)
        self.assertIn("~/.ssh", r.stdout)
        self.assertFalse(os.path.exists(self.dest))

    def test_without_age_fails_and_leaves_nothing(self):
        r = self.run_sh("--full", self.dest, path="/usr/bin:/bin")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("age", r.stderr)
        self.assertFalse(os.path.exists(self.dest) and os.listdir(self.dest))

    def test_allowlist_only(self):
        age_file, _ = self.make()
        names = self.names(age_file)
        self.assertIn(".gitconfig", names)
        self.assertIn("Dev/handoffs/a.md", names)
        self.assertIn(".claude/projects/p1/memory/m.md", names)
        self.assertIn("Dev/side-project/brand.md", names)
        for bad in (".ssh/id_ed25519", ".config/gh/hosts.yml", ".claude.json", ".claude/projects/p1/session.jsonl",
                    "Dev/side-project/models/big.bin", "Dev/side-project/exports/big.mp4"):
            self.assertNotIn(bad, names)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "RESTORE.md")))
        self.assertNotIn("SECRET", open(age_file, "rb").read().decode("latin1"))

    def test_round_trip_and_no_overwrite(self):
        age_file, _ = self.make()
        with tempfile.TemporaryDirectory() as out:
            r = self.run_sh("--restore", age_file, "--home", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(open(f"{out}/Dev/handoffs/a.md").read(), "handoff")
            self.assertEqual(open(f"{out}/.claude/projects/p1/memory/m.md").read(), "memory")
            write(f"{out}/.gitconfig", "changed")
            r = self.run_sh("--restore", age_file, "--home", out)
            self.assertIn(".gitconfig", r.stdout)
            self.assertEqual(open(f"{out}/.gitconfig").read(), "changed")
            self.run_sh("--restore", age_file, "--home", out, "--force")
            self.assertEqual(open(f"{out}/.gitconfig").read(), "[user]")
            self.assertEqual(open(f"{out}/.gitconfig.bak").read(), "changed")

    def test_dirty_repo_warns_without_blocking(self):
        repo = os.path.join(self.home, "Dev/repos/r")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q", repo], check=True)
        write(f"{repo}/f", "dirty")
        r = self.run_sh("--full", self.dest, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("r: uncommitted changes", r.stdout)


class BackupPolicy(unittest.TestCase):
    """The personal folders come from a layer's policy `backup`; with none, no personal folder is backed up."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.home = os.path.join(self._t.name, "home")
        for rel in ("Dev/notes/a.md", "Dev/notes/skip/b.md", "Dev/other/c.md", ".gitconfig"):
            write(os.path.join(self.home, rel))
        write(os.path.join(self.home, ".secret-thing/k"), "SECRET")

    def tearDown(self):
        self._t.cleanup()

    def rels(self, policy):
        files, _ = backup_full.expand(self.home, policy)
        return sorted(r for _, r, _ in files)

    def test_layer_include_and_exclude_are_exact(self):
        policy = {"dev_root": "~/Dev", "backup": {"include": ["{{DEV}}/notes"], "exclude": ["{{DEV}}/notes/skip"]}}
        got = self.rels(policy)
        self.assertIn("Dev/notes/a.md", got)
        self.assertNotIn("Dev/notes/skip/b.md", got)
        self.assertNotIn("Dev/other/c.md", got)
        self.assertIn(".gitconfig", got)  # the generic items stay

    def test_no_layer_backs_up_no_personal_folder(self):
        got = self.rels({})
        self.assertEqual(got, [".gitconfig"])
        with open(backup_full.__file__) as f:
            self.assertNotIn("instagram", f.read().lower())

    def test_no_layer_does_not_resolve_dev_folders_to_home(self):
        write(os.path.join(self.home, "handoffs/h.md"))
        write(os.path.join(self.home, "ai-notes/n.md"))
        self.assertEqual(self.rels({}), [".gitconfig"])
        got = self.rels({"dev_root": "~/Dev"})  # with a dev_root they live under it
        self.assertNotIn("handoffs/h.md", got)
        write(os.path.join(self.home, "Dev/handoffs/d.md"))
        self.assertIn("Dev/handoffs/d.md", self.rels({"dev_root": "~/Dev"}))

    def test_by_hand_comes_from_the_layer(self):
        items = backup_full.by_hand_items(self.home, {"backup": {"by_hand": [[".secret-thing", "my secret"]]}})
        self.assertIn((".secret-thing", "my secret"), items)
        self.assertNotIn(".secret-thing", [p for p, _ in backup_full.by_hand_items(self.home, {})])


if __name__ == "__main__":
    unittest.main()
