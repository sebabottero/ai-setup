"""add-skill writes to the layer's real folder, including layers kept outside this repo (--layers-dir in the profile)."""
import json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, ROOT)
import add_skill, layers


class ExternalLayer(unittest.TestCase):
    def setUp(self):
        self.extra, self.home = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(self.extra, "acme", "skills", "x"))
        with open(os.path.join(self.extra, "acme", "skills", "x", "SKILL.md"), "w") as f:
            f.write("---\nname: x\ndescription: d\n---\n")
        with open(os.path.join(self.home, ".ai-setup-profile"), "w") as f:
            json.dump({"layers": ["core", "acme"], "layers_dirs": [self.extra]}, f)

    def tearDown(self):
        layers.set_extra_roots([])
        for d in (self.extra, self.home):
            shutil.rmtree(d, ignore_errors=True)

    def test_profile_folders_are_used(self):
        add_skill.use_profile_layers(self.home)
        self.assertIn("acme", layers.present(ROOT))
        add_skill.set_layer("acme")
        self.assertEqual(add_skill.SKILLS, os.path.join(os.path.realpath(self.extra), "acme", "skills"))

    def test_core_stays_in_this_repo(self):
        add_skill.use_profile_layers(self.home)
        add_skill.set_layer("core")
        self.assertEqual(add_skill.SKILLS, os.path.join(ROOT, "core", "skills"))


if __name__ == "__main__":
    unittest.main()
