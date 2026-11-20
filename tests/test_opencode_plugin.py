"""adapters/opencode/plugins/ai-setup-guard.js: with a fake OpenCode context, a risky bash permission must come back as
ask / deny. This tests our side of the beta plugin API (setup -> permission.hook("evaluate") -> event.effect); it cannot
tell whether a new OpenCode still calls the hook: after updating it, run `git push` in a session and check it prompts."""
import os, shutil, subprocess, sys, tempfile, unittest

os.environ["AI_SETUP_GUARD_LOG"] = "off"  # the plugin runs the real guard: keep the tests out of ~/.ai-setup
os.environ["AI_SETUP_ACTIONS_LOG"] = "off"  # and out of <dev_root>/logs/actions.log

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PLUGIN = os.path.join(ROOT, "adapters", "opencode", "plugins", "ai-setup-guard.js")
DRIVER = """
import plugin from "%s"
const handlers = {}
const hook = await plugin.setup({ permission: { hook: async (name, fn) => { handlers[name] = fn } } })
const out = []
for (const command of JSON.parse(process.argv[2])) {
  const event = { action: "bash", resources: [command] }
  handlers.evaluate(event)
  out.push(event.effect || "allow")
}
console.log(JSON.stringify(out))
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Plugin(unittest.TestCase):
    def run_plugin(self, commands, env=None):
        with tempfile.TemporaryDirectory() as tmp:
            with open(PLUGIN) as f:  # the installer replaces {{AI_SETUP}}; do the same into a temp copy
                code = f.read().replace("{{AI_SETUP}}", ROOT)
            plugin = os.path.join(tmp, "plugin.mjs")
            driver = os.path.join(tmp, "driver.mjs")
            with open(plugin, "w") as f:
                f.write(code)
            with open(driver, "w") as f:
                f.write(DRIVER % plugin)
            out = subprocess.run(["node", driver, __import__("json").dumps(commands)], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return __import__("json").loads(out.stdout)

    def test_risky_commands_ask_and_everyday_ones_pass(self):
        self.assertEqual(self.run_plugin(["git push origin main", "git status", "bash -c 'git push'"]), ["ask", "allow", "ask"])

    def test_the_suite_does_not_write_the_real_actions_log(self):
        with tempfile.TemporaryDirectory() as home:  # a leak would land in <home>/**/logs/actions.log, never in the real one
            self.assertEqual(self.run_plugin(["git push origin main"], env=dict(os.environ, HOME=home)), ["ask"])
            leaked = [os.path.join(d, n) for d, _, names in os.walk(home) for n in names if n.startswith("actions.log")]
        self.assertEqual(leaked, [])
        with tempfile.TemporaryDirectory() as tmp:  # and the log still works when pointed at a file
            log = os.path.join(tmp, "actions.log")
            self.run_plugin(["git push origin main"], env=dict(os.environ, AI_SETUP_ACTIONS_LOG=log))
            with open(log) as f:
                self.assertIn("git push origin main", f.read())

    def test_secrets_are_denied(self):
        self.assertEqual(self.run_plugin(["cat ~/.ssh/id_rsa"]), ["deny"])

    def test_an_api_without_the_hook_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin = os.path.join(tmp, "plugin.mjs")
            with open(PLUGIN) as f, open(plugin, "w") as g:
                g.write(f.read().replace("{{AI_SETUP}}", ROOT))
            driver = os.path.join(tmp, "d.mjs")
            with open(driver, "w") as f:
                f.write('import p from "%s"; await p.setup({}); console.log("ok")' % plugin)
            out = subprocess.run(["node", driver], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
