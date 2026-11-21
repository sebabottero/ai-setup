"""Smoke test: a full install into a throwaway home, for every tool, then a second run that changes nothing."""
import json, os, subprocess, sys, tempfile, unittest
from unittest import mock

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

    def test_action_trace_is_a_pretooluse_bash_hook(self):
        groups = self.load(".claude", "settings.json")["hooks"]["PreToolUse"]
        hit = [g for g in groups for h in g["hooks"] if "action_trace.py" in h["command"]]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["matcher"], "Bash")
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", "hooks", "action_trace.py")))

    def test_claude(self):
        s = self.load(".claude", "settings.json")
        commands = [h["command"] for groups in s["hooks"].values() for g in groups for h in g["hooks"]]
        self.assertTrue(any("policy_guard.py" in c for c in commands))
        self.assertTrue(any("context_notice.py" in c for c in commands))
        self.assertTrue(any("tune_notice.py" in c for c in commands))
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", "hooks", "policy_guard.py")))
        self.assertEqual(s["permissions"]["defaultMode"], "auto")
        self.assertEqual(s["model"], "opusplan")  # Opus to plan, Sonnet to execute
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")  # general-purpose does not inherit Opus
        self.assertIn("\neffort: high\n", self.text(".claude", "agents", "sub-review.md"))
        self.assertIn("\neffort: low\n", self.text(".claude", "agents", "leaf-verify.md"))
        self.assertNotIn("effort:", self.text(".claude", "agents", "sub-tester.md"))
        self.assertIn("sonnet", self.text(".claude", "agents", "sub-builder.md"))  # the writer runs on the balanced model
        self.assertIn(f"Edit(/{ROOT}/core/policy.json)", s["permissions"]["ask"])
        self.assertFalse([r for r in s["permissions"]["ask"] if r.startswith("Bash(")])  # a native rule would hide the guard's label
        box = s["sandbox"]
        self.assertTrue(box["enabled"])
        self.assertFalse(box["allowUnsandboxedCommands"])  # core never opts in: only a layer's policy can
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


class RetiredHooks(unittest.TestCase):
    OLD = {"type": "command", "command": 'python3 -I "$HOME/.claude/hooks/drive_trace.py"', "timeout": 5}
    USER = {"type": "command", "command": "my-own-hook.sh"}

    def test_old_entry_is_dropped_and_user_hooks_stay(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".claude"))
        path = os.path.join(home, ".claude", "settings.json")
        with open(path, "w") as f:
            json.dump({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [self.OLD]},
                                                {"matcher": "Bash", "hooks": [self.USER, dict(self.OLD)]}]}}, f)
        self.assertEqual(install(home).returncode, 0)
        with open(path) as f:
            first = f.read()
        hooks = json.loads(first)["hooks"]["PreToolUse"]
        commands = [h["command"] for g in hooks for h in g["hooks"]]
        self.assertFalse([c for c in commands if "drive_trace.py" in c])
        self.assertIn("my-own-hook.sh", commands)
        self.assertTrue([c for c in commands if "policy_guard.py" in c])
        self.assertTrue(all(g["hooks"] for g in hooks))
        self.assertEqual(install(home).returncode, 0)
        with open(path) as f:
            self.assertEqual(f.read(), first)


class GuardCheck(unittest.TestCase):
    def test_the_hook_asks_for_a_push(self):
        sys.path.insert(0, ROOT)
        import install
        self.assertIsNone(install.guard_problem())

    def test_a_missing_hook_is_a_problem(self):
        sys.path.insert(0, ROOT)
        import install
        real = install.ADAPTERS
        install.ADAPTERS = os.path.join(tempfile.mkdtemp(), "nowhere")
        try:
            self.assertIsNotNone(install.guard_problem())
        finally:
            install.ADAPTERS = real


class PushAllowRules(unittest.TestCase):
    """D13: push_allow becomes Claude permissions.allow rules for the same pushes the guard lets run; the hook still asks on a tainted line."""
    ALLOW = {"remotes": ["origin", "fork"], "branches": ["ai/*", "release"]}

    def setUp(self):
        sys.path.insert(0, ROOT)
        sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
        import install, layers
        self.install, self.layers = install, layers
        patch = mock.patch.object(install, "HOME", "/Users/x")  # set by main() in a real run
        patch.start()
        self.addCleanup(patch.stop)
        self.core = layers.compose_policy(ROOT, ["core"])

    def rules(self, allow):
        return [r for r in self.install.claude_lists(dict(self.core, push_allow=allow))[("permissions", "allow")] if r.startswith("Bash(git push ")]

    def test_each_remote_and_branch_gets_a_rule_and_the_upstream_variants(self):
        rules = self.rules(self.ALLOW)
        self.assertEqual(len(rules), 2 * 2 * 3)
        for r in ["Bash(git push origin ai/*)", "Bash(git push -u origin ai/*)", "Bash(git push --set-upstream origin ai/*)",
                  "Bash(git push fork release)", "Bash(git push -u fork release)", "Bash(git push --set-upstream origin release)"]:
            self.assertIn(r, rules)

    def test_none_without_push_allow(self):
        self.assertEqual(self.rules({}), [])
        self.assertEqual(self.rules({"remotes": ["origin"]}), [])
        self.assertEqual(self.rules({"branches": ["ai/*"]}), [])
        self.assertEqual([r for r in self.install.claude_lists(self.core)[("permissions", "allow")] if "git push" in r], [])

    def test_only_a_literal_branch_or_a_prefix_glob_with_safe_characters(self):
        branches = ["*", "ai*", "*/x", "a?b", "a[bc]", "ai/**", "ai/*/x", "ai/x y", "a;b", "a$B", "ai/`x`", "(x)", "a'b", "-f", "", "ai/..", "ai/x\\n", "/*"]
        self.assertEqual(self.rules({"remotes": ["origin"], "branches": branches}), [])
        self.assertEqual(self.rules({"remotes": ["or igin", "o;x", "*", "o*", "-u", ""], "branches": ["ai/*"]}), [])
        self.assertEqual(len(self.rules({"remotes": ["origin"], "branches": ["ai/*", "my-topic", "a.b/c_d/*"]})), 9)

    def test_every_generated_rule_is_allowed_by_the_guard(self):
        self.assertEqual(self.install.lint_policy(dict(self.core, push_allow=self.ALLOW)), [])

    def test_a_branch_the_guard_rejects_gets_no_rule_and_does_not_fail_the_lint(self):
        allow = {"remotes": ["origin"], "branches": ["x.lock", "ai/x.", "refs/heads/ai/*"]}
        self.assertEqual(self.rules(allow), [])
        self.assertEqual(len(self.rules(dict(allow, branches=["x.lock", "ai/*"]))), 3)  # ai/* is kept
        self.assertEqual(self.install.lint_policy(dict(self.core, push_allow=allow)), [])

    def test_a_policy_with_such_branches_still_installs(self):
        home, layers_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(layers_dir, "odd"))
        with open(os.path.join(layers_dir, "odd", "policy.json"), "w") as f:
            json.dump({"push_allow": {"remotes": ["origin"], "branches": ["x.lock", "ai/x.", "refs/heads/ai/*"]}}, f)
        done = install(home, "--layers-dir", layers_dir, "--with", "odd")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(os.path.join(home, ".claude", "settings.json")) as f:
            self.assertEqual([r for r in json.load(f)["permissions"]["allow"] if "git push" in r], [])

    def test_install_adds_the_rules_and_uninstall_subtracts_them(self):
        home, layers_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        os.makedirs(os.path.join(layers_dir, "pusher"))
        with open(os.path.join(layers_dir, "pusher", "policy.json"), "w") as f:
            json.dump({"push_allow": {"remotes": ["origin"], "branches": ["ai/*"]}}, f)
        path = os.path.join(home, ".claude", "settings.json")

        def allow():
            with open(path) as f:
                return json.load(f)["permissions"]["allow"]
        done = install(home, "--layers-dir", layers_dir, "--with", "pusher")
        self.assertEqual(done.returncode, 0, done.stderr)
        for r in ["Bash(git push origin ai/*)", "Bash(git push -u origin ai/*)", "Bash(git push --set-upstream origin ai/*)"]:
            self.assertIn(r, allow())
        gone = install(home, "--layers-dir", layers_dir, "--uninstall", "pusher")
        self.assertEqual(gone.returncode, 0, gone.stderr)
        self.assertEqual([r for r in allow() if "git push" in r], [])


class UnsandboxedOptIn(unittest.TestCase):
    def test_off_unless_a_layer_opts_in(self):
        sys.path.insert(0, ROOT)
        import install
        self.assertFalse(install.allow_unsandboxed({}))
        self.assertFalse(install.allow_unsandboxed({"sandbox": {"allow_unsandboxed_commands": False}}))
        self.assertFalse(install.allow_unsandboxed({"sandbox": {"allow_unsandboxed_commands": "yes"}}))
        self.assertTrue(install.allow_unsandboxed({"sandbox": {"allow_unsandboxed_commands": True}}))

    def test_layers_merge_with_or(self):
        sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
        import layers
        merged = layers.merge_policies([{"sandbox": {"allow_unsandboxed_commands": False}},
                                        {"sandbox": {"allow_unsandboxed_commands": True}}])
        self.assertTrue(merged["sandbox"]["allow_unsandboxed_commands"])


class Collisions(unittest.TestCase):
    def test_adapter_cannot_shadow_core(self):
        sys.path.insert(0, ROOT)
        import install as inst
        self.assertEqual(inst.collisions({"validate": 1, "grillme": 1}, {"validate": 1, "extra": 1}), ["validate"])


if __name__ == "__main__":
    unittest.main()
