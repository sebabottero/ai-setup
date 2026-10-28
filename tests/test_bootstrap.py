"""bootstrap.py: --only core leaves other layers' toolchain out, every layer lists what it needs, backup can exclude a layer.
The layers used here are fixtures (tests/fixtures/layers), loaded through --layers-dir."""
import json, os, subprocess, sys, tempfile, unittest, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "layers")
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import layers


def bootstrap(home, *extra):
    return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "bootstrap.py"), "--dry-run", "--home", home, "--layers-dir", FIXTURES, *extra],
                          capture_output=True, text=True)


class Manifests(unittest.TestCase):
    def test_manifests_are_valid(self):
        layers.set_extra_roots([FIXTURES])
        self.addCleanup(layers.set_extra_roots, [])
        for layer in layers.present(ROOT):
            path = os.path.join(layers.layer_dir(ROOT, layer), "bootstrap.json")
            if os.path.exists(path):
                with open(path) as f:
                    m = json.load(f)
                for s in m.get("steps", []):
                    self.assertTrue({"name", "check", "run"} <= set(s), f"{layer}: step incompleto {s}")


class DryRun(unittest.TestCase):
    def test_work_layer_is_optional(self):
        with tempfile.TemporaryDirectory() as home:
            without = bootstrap(home, "--only", "core,me")
            self.assertEqual(without.returncode, 0, without.stderr)
            self.assertNotIn("Work SDK", without.stdout)
            self.assertNotIn("tea login", without.stdout)
            full = bootstrap(home, "--only", "core,work")
            self.assertIn("Work SDK 1.2.3", full.stdout)
            self.assertIn("tea login add", full.stdout)

    def test_unknown_layer_stops(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertNotEqual(bootstrap(home, "--only", "nope").returncode, 0)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            bootstrap(home, "--only", "core")
            self.assertEqual(os.listdir(home), [])


class Backup(unittest.TestCase):
    def test_zip_without_a_layer(self):
        with tempfile.TemporaryDirectory() as out:
            r = subprocess.run([os.path.join(ROOT, "backup.sh"), "--without", "docs", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            names = zipfile.ZipFile(os.path.join(out, os.listdir(out)[0])).namelist()
            self.assertFalse([n for n in names if "/docs/" in n or "/.git/" in n])
            self.assertTrue([n for n in names if n.endswith("/install.py")])


if __name__ == "__main__":
    unittest.main()
