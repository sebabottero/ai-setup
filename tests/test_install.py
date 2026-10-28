"""Smoke test: a full install into a throwaway home, for every tool, then a second run that changes nothing."""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "layers")  # a `work` layer with sandbox settings


BUILD = tempfile.mkdtemp()  # keep the real build/ (read by the running guard) out of the tests


def install(home, *extra):
    return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "install.py"), "--home", home, "--build", BUILD,
                           "--tools", "claude,opencode,codex", "--layers-dir", FIXTURES, *extra], capture_output=True, text=True)


class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.run1 = install(cls.home)

    def text(self, *path):
        with open(os.path.join(self.home, *path)) as f:
            return f.read()

    def load(self, *path):
        return json.loads(self.text(*path))

    def test_runs(self):
        self.assertEqual(self.run1.returncode, 0, self.run1.stderr)

    def test_claude(self):
        s = self.load(".claude", "settings.json")
        commands = [h["command"] for groups in s["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertTrue(any("policy_guard.py" in c for c in commands))
        self.assertTrue(any("context_notice.py" in c for c in commands))
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", "hooks", "policy_guard.py")))
        self.assertEqual(s["permissions"]["defaultMode"], "auto")
        self.assertEqual(s["model"], "opusplan")  # Opus to plan, Sonnet to execute
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")  # general-purpose does not inherit Opus
        self.assertIn("\neffort: high\n", self.text(".claude", "agents", "sub-review.md"))
        self.assertIn("\neffort: low\n", self.text(".claude", "agents", "leaf-verify.md"))
        self.assertNotIn("effort:", self.text(".claude", "agents", "sub-tester.md"))
        self.assertIn("sonnet", self.text(".claude", "agents", "sub-builder.md"))  # the writer runs on the balanced model
        self.assertIn(f"Edit(/{ROOT}/core/policy.json)", s["permissions"]["ask"])
        box = s["sandbox"]
        self.assertTrue(box["enabled"])
        self.assertFalse(box["allowUnsandboxedCommands"])
        self.assertNotIn("docker *", box["excludedCommands"])
        self.assertIn("~/**/.env.local", box["filesystem"]["denyRead"])
        self.assertIn(f"{ROOT}/core/guard/**", box["filesystem"]["denyWrite"])
        self.assertIn("github.com", box["network"]["allowedDomains"])
        self.assertIn("~/.local/share/NuGet", box["filesystem"]["allowWrite"])  # the work fixture layer adds it
        self.assertTrue(box["enableWeakerNetworkIsolation"])  # set by the work fixture layer
        self.assertTrue(os.path.isfile(os.path.join(self.home, ".claude", "skills", "ticket-flow", "SKILL.md")))

    def test_opencode(self):
        c = self.load(".config", "opencode", "opencode.json")
        self.assertEqual(c["share"], "disabled")
        self.assertIn(os.path.join(ROOT, "core", "skills"), c["skills"])
        self.assertIn({"action": "edit", "resource": f"{ROOT}/core/policy.json", "effect": "ask"}, c["permissions"])
        plugin = self.text(".config", "opencode", "plugins", "ai-setup-guard.js")
        self.assertIn(os.path.join(ROOT, "core", "guard", "guard.py"), plugin)
        meta = self.text(".config", "opencode", "agents", "meta-setup.md")
        self.assertLess(meta.index('"allow"'), meta.index(f'"{ROOT}/core/policy.json", effect: "ask"'))

    def test_codex(self):
        self.assertTrue(os.path.islink(os.path.join(self.home, ".codex", "AGENTS.md")))
        skills = os.path.join(self.home, ".codex", "skills")
        self.assertTrue(os.path.islink(os.path.join(skills, "ticket-flow")))  # a core skill
        self.assertTrue(os.path.islink(os.path.join(skills, "me-skill")))  # a fixture layer's skill
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex", "agents")))  # Codex gets no agents or guard

    def test_second_run_changes_nothing(self):
        out = install(self.home).stdout
        self.assertNotRegex(out, r"(?m)^(write|link|backup|remove) ")


class Collisions(unittest.TestCase):
    def test_adapter_cannot_shadow_core(self):
        sys.path.insert(0, ROOT)
        import install as inst
        self.assertEqual(inst.collisions({"validate": 1, "grillme": 1}, {"validate": 1, "extra": 1}), ["validate"])


if __name__ == "__main__":
    unittest.main()
