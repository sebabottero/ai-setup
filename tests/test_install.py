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


class OpencodeSandbox(unittest.TestCase):
    """Criterion 13: an opt-in srt wall for OpenCode, built from policy.json; off = nothing changes."""
    @classmethod
    def setUpClass(cls):
        cls.off, cls.on = tempfile.mkdtemp(), tempfile.mkdtemp()
        cls.run_off, cls.run_on = install(cls.off), install(cls.on, "--opencode-sandbox")

    def files(self, home):
        out = {}
        for d, _, names in os.walk(home):
            if ".ai-setup-backups" in d:
                continue
            for n in names:
                p = os.path.join(d, n)
                if os.path.islink(p):
                    text = os.readlink(p)
                else:
                    with open(p) as f:
                        text = f.read()
                out[os.path.relpath(p, home)] = text.replace(home, "<home>")
        return out

    def test_both_runs_succeed(self):
        self.assertEqual(self.run_off.returncode, 0, self.run_off.stderr)
        self.assertEqual(self.run_on.returncode, 0, self.run_on.stderr)

    def test_off_writes_no_sandbox_files(self):
        self.assertFalse(os.path.exists(os.path.join(self.off, ".ai-setup")))

    def test_on_only_adds_the_two_files(self):
        off, on = self.files(self.off), self.files(self.on)
        added = sorted(set(on) - set(off))
        self.assertEqual(added, [os.path.join(".ai-setup", "bin", "opencode-sandboxed"),
                                 os.path.join(".ai-setup", "opencode-sandbox.json")])
        self.assertEqual({k: v for k, v in on.items() if k in off}, off)  # everything else is identical: default unchanged

    def test_settings_come_from_the_policy(self):
        with open(os.path.join(self.on, ".ai-setup", "opencode-sandbox.json")) as f:
            cfg = json.load(f)
        with open(os.path.join(self.on, ".claude", "settings.json")) as f:
            claude = json.load(f)["sandbox"]
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "adapters", "opencode", "sandbox", "extra.json")) as f:
            extra = json.load(f)
        self.assertEqual(cfg["network"]["allowedDomains"], claude["network"]["allowedDomains"] + extra["extra_domains"])  # Claude's list exactly, then OpenCode's own hosts, nothing else
        self.assertEqual(cfg["filesystem"]["denyWrite"], claude["filesystem"]["denyWrite"])
        self.assertIn(os.path.join(self.on, ".ssh"), cfg["filesystem"]["denyRead"])
        self.assertIn(os.path.join(self.on, ".local/share/NuGet"), cfg["filesystem"]["allowWrite"])  # the work fixture layer adds it
        self.assertTrue(any(p.startswith(self.on + "/**/") for p in cfg["filesystem"]["denyRead"]))  # secret files, anywhere under home

    def test_launcher_runs_srt_with_the_settings_and_is_marked(self):
        launcher = os.path.join(self.on, ".ai-setup", "bin", "opencode-sandboxed")
        with open(launcher) as f:
            text = f.read()
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn(os.path.join(self.on, ".ai-setup", "opencode-sandbox.json"), text)
        self.assertIn("srt --settings", text)
        self.assertIn("TO VERIFY", text)
        self.assertNotIn("{{", text)

    def test_opencode_needs_are_added(self):
        with open(os.path.join(self.on, ".ai-setup", "opencode-sandbox.json")) as f:
            cfg = json.load(f)
        for d in (".local/share/opencode", ".config/opencode", ".cache/opencode", ".local/state/opencode"):
            self.assertIn(os.path.join(self.on, d), cfg["filesystem"]["allowWrite"])
        self.assertNotIn(".", cfg["filesystem"]["allowWrite"])
        self.assertIn("api.anthropic.com", cfg["network"]["allowedDomains"])

    def test_launcher_adds_the_project_dir_and_quotes_the_settings_path(self):
        home = os.path.join(tempfile.mkdtemp(), "a b")  # a space in the path
        os.makedirs(home)
        self.assertEqual(install(home, "--opencode-sandbox").returncode, 0)
        bin_dir, proj = tempfile.mkdtemp(), tempfile.mkdtemp()
        fake = os.path.join(bin_dir, "srt")  # stands in for srt: prints the settings it was given
        with open(fake, "w") as f:
            f.write('#!/bin/sh\ncat "$2"\n')
        os.chmod(fake, 0o755)
        env = {**os.environ, "PATH": bin_dir + os.pathsep + os.environ["PATH"]}
        r = subprocess.run([os.path.join(home, ".ai-setup", "bin", "opencode-sandboxed")], cwd=proj, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(os.path.realpath(proj), json.loads(r.stdout)["filesystem"]["allowWrite"])

    def test_warns_when_opencode_is_not_installed(self):
        home = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "install.py"), "--home", home, "--build", BUILD,
                            "--tools", "claude", "--layers-dir", FIXTURES, "--opencode-sandbox"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--opencode-sandbox", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(home, ".ai-setup")))

    def test_dry_run_writes_nothing(self):
        home = tempfile.mkdtemp()
        self.assertEqual(install(home, "--opencode-sandbox", "--dry-run").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(home, ".ai-setup")))


class Collisions(unittest.TestCase):
    def test_adapter_cannot_shadow_core(self):
        sys.path.insert(0, ROOT)
        import install as inst
        self.assertEqual(inst.collisions({"validate": 1, "grillme": 1}, {"validate": 1, "extra": 1}), ["validate"])


if __name__ == "__main__":
    unittest.main()
