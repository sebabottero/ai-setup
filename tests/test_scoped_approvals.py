"""Criterion 12 (variant E): inside a ticket worktree (<dev root>/worktrees/<repo>/<ticket>/) a protected path that the
ticket's scope file names exactly asks once, every other protected path asks every time, and anything else gets no
opinion from the hook. The scope file is written only by core/guard/scope.py, which the guard asks about."""
import json, os, subprocess, sys, tempfile, unittest
from unittest import mock

os.environ["AI_SETUP_GUARD_LOG"] = "off"
os.environ["AI_SETUP_ACTIONS_LOG"] = "off"

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "scoped_edit.py")
SESSION_HOOK = os.path.join(ROOT, "adapters", "claude", "hooks", "ask_outcome.py")
SCOPE = os.path.join(ROOT, "core", "guard", "scope.py")
sys.path.insert(0, os.path.join(ROOT, "core", "guard"))
import guard, scope

REPO = os.path.basename(ROOT)  # the protected globs are the setup's own: only worktrees of this repo use them
POLICY = {"dev_root": "~", "protected_paths": ["{{AI_SETUP}}/core/guard/*", "{{AI_SETUP}}/install.py",
                                                "~/.config/opencode/opencode.json"]}
GUARDED = "core/guard/guard.py"


def touch(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.base = os.path.join(self.tmp, "worktrees")
        self.wt = os.path.join(self.base, REPO, "t1")
        self.other = os.path.join(self.base, REPO, "t2")
        self.main = os.path.join(self.tmp, "main")
        for root in (self.wt, self.other, self.main):
            for rel in (GUARDED, "core/guard/other.py", "install.py", "README.md", "tests/a.py"):
                touch(os.path.join(root, rel))
        self.scopes = os.path.join(self.tmp, "scopes")
        self.env = dict(os.environ, AI_SETUP_WORKTREES=self.base, AI_SETUP_SCOPES_DIR=self.scopes,
                        AI_SETUP_GUARD_LOG="off", HOME=self.tmp)
        patch = mock.patch.dict(os.environ, {"AI_SETUP_WORKTREES": self.base, "AI_SETUP_SCOPES_DIR": self.scopes})
        patch.start()
        self.addCleanup(patch.stop)

    def event(self, path, tool="Edit", use="u1", kind="PreToolUse", cwd=None):
        return {"hook_event_name": kind, "tool_name": tool, "tool_input": {"file_path": path}, "tool_use_id": use,
                "cwd": cwd or self.wt, "session_id": "s1"}

    def check(self, path, **kw):
        result = scope.check(self.event(path, **kw), POLICY)
        return result and result[0]

    def approve(self, path, use="u1"):
        """The first ask was answered yes: the tool ran, PostToolUse fires."""
        scope.after(self.event(path, use=use, kind="PostToolUse"))

    def add(self, *paths, wt=None):
        scope.add(wt or self.wt, list(paths))

    def hook(self, event, env=None, raw=None):
        out = subprocess.run([sys.executable, "-I", HOOK], input=raw if raw is not None else json.dumps(event),
                             capture_output=True, text=True, env=env or self.env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)["hookSpecificOutput"] if out.stdout.strip() else None


class Decisions(Base):
    def test_exact_scope_path_asks_before_the_grant_and_is_allowed_after(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        self.assertEqual(self.check(path), "ask")
        self.assertEqual(self.check(path), "ask")  # still no grant: the first ask was not answered
        self.approve(path)
        self.assertEqual(self.check(path), "allow")
        self.assertEqual(self.check(path, tool="Write", use="u9"), "allow")

    def test_no_grant_without_post_tool_use_success_for_that_ask(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        self.check(path)
        self.approve(path, use="never-asked")  # a PostToolUse with no matching ask
        self.assertEqual(self.check(path, use="u2"), "ask")
        self.approve(os.path.join(self.wt, "README.md"), use="u2")  # another path: not this ask's
        self.assertEqual(self.check(path, use="u3"), "ask")

    def test_a_grant_is_not_given_by_a_second_post_tool_use(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        self.check(path)
        self.approve(path)
        self.approve(path)  # the marker is consumed: nothing breaks
        self.assertEqual(self.check(path), "allow")

    def test_other_protected_paths_ask_every_time(self):
        self.add(GUARDED)
        for rel in ("install.py", "core/guard/other.py"):
            path = os.path.join(self.wt, rel)
            self.assertEqual(self.check(path), "ask", rel)
            self.approve(path)
            self.assertEqual(self.check(path), "ask", rel)  # no scope entry, so never a grant

    def test_a_granted_path_does_not_grant_its_neighbours(self):
        self.add(GUARDED)
        self.check(os.path.join(self.wt, GUARDED))
        self.approve(os.path.join(self.wt, GUARDED))
        self.assertEqual(self.check(os.path.join(self.wt, "core/guard/other.py")), "ask")

    def test_no_scope_file_means_every_protected_path_asks(self):
        self.assertEqual(self.check(os.path.join(self.wt, GUARDED)), "ask")

    def test_outside_the_worktree_and_non_protected_paths_get_no_opinion(self):
        self.add(GUARDED)
        self.assertIsNone(self.check(os.path.join(self.main, GUARDED)))  # the main checkout keeps its native rule
        self.assertIsNone(self.check(os.path.join(self.wt, "README.md")))
        self.assertIsNone(self.check(os.path.join(self.wt, "tests/a.py")))
        self.assertIsNone(self.check(os.path.join(self.tmp, "elsewhere.py")))
        self.assertIsNone(self.check(os.path.join(self.base, REPO, "t1")))  # a folder, not a file in a ticket worktree
        stranger = os.path.join(self.base, "other-repo", "t1", "install.py")  # another repo: its install.py is not ours
        touch(stranger)
        self.assertIsNone(self.check(stranger, cwd=os.path.dirname(stranger)))

    def test_a_relative_path_is_taken_from_the_event_cwd(self):
        self.add(GUARDED)
        self.assertEqual(self.check(GUARDED), "ask")
        self.assertIsNone(self.check("README.md"))

    def test_dotdot_never_earns_an_allow(self):
        self.add(GUARDED)
        real = os.path.join(self.wt, GUARDED)
        self.check(real)
        self.approve(real)
        self.assertEqual(self.check(real), "allow")
        sneaky = os.path.join(self.wt, "tests", "..", GUARDED)
        self.assertEqual(self.check(sneaky), "ask")
        escape = os.path.join(self.wt, "..", "t2", GUARDED)  # lands in the other worktree
        self.assertEqual(self.check(escape), "ask")

    def test_a_symlink_that_leaves_the_worktree_asks(self):
        self.add(GUARDED, "link.py")
        os.symlink(os.path.join(self.main, GUARDED), os.path.join(self.wt, "link.py"))
        os.symlink(os.path.join(self.main, "core"), os.path.join(self.wt, "dirlink"))
        self.assertEqual(self.check(os.path.join(self.wt, "link.py")), "ask")
        self.assertEqual(self.check(os.path.join(self.wt, "dirlink", "guard", "guard.py")), "ask")
        self.approve(os.path.join(self.wt, "link.py"))
        self.assertEqual(self.check(os.path.join(self.wt, "link.py")), "ask")  # never a grant either

    def test_a_symlink_to_a_protected_file_is_judged_by_its_target(self):
        os.symlink(os.path.join(self.wt, GUARDED), os.path.join(self.wt, "alias.py"))
        self.assertEqual(self.check(os.path.join(self.wt, "alias.py")), "ask")  # not in scope: the target is protected

    def test_the_case_of_a_path_does_not_hide_it(self):
        self.add(GUARDED)
        self.assertEqual(self.check(os.path.join(self.wt, "Core", "Guard", "guard.py")), "ask")
        self.assertEqual(self.check(os.path.join(self.wt, "INSTALL.PY")), "ask")

    def test_a_scope_file_for_another_worktree_does_not_apply(self):
        self.add(GUARDED, wt=self.other)
        path_other, path = os.path.join(self.other, GUARDED), os.path.join(self.wt, GUARDED)
        self.check(path_other, cwd=self.other)
        self.approve(path_other)
        self.assertEqual(self.check(path_other, cwd=self.other), "allow")
        self.assertEqual(self.check(path), "ask")
        # a scope file copied under this worktree's name still names the other one: ignored
        src, dst = scope.scope_file(self.other), scope.scope_file(self.wt)
        with open(src) as a, open(dst, "w") as b:
            b.write(a.read())
        self.assertEqual(self.check(path), "ask")

    def test_a_corrupt_scope_or_grant_file_asks(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        self.check(path)
        self.approve(path)
        for f in (scope.scope_file(self.wt), scope.grants_file(self.wt)):
            with open(f, "w") as fh:
                fh.write("{not json")
        self.assertEqual(self.check(path), "ask")

    def test_the_scopes_folder_itself_asks_every_time(self):
        self.assertEqual(self.check(os.path.join(self.scopes, "x.json")), "ask")

    def test_add_forgets_an_old_grant(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        self.check(path)
        self.approve(path)
        self.add(GUARDED)  # a new Gate 1: one more ask
        self.assertEqual(self.check(path), "ask")


class ScopeCommand(Base):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", SCOPE, *args], capture_output=True, text=True, env=self.env, timeout=30)

    def test_add_show_clear(self):
        out = self.run_cli("add", self.wt, GUARDED, "install.py")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(sorted(scope.read_scope(self.wt)), ["core/guard/guard.py", "install.py"])
        self.assertIn(GUARDED, self.run_cli("show", self.wt).stdout)
        self.assertEqual(self.run_cli("clear", self.wt).returncode, 0)
        self.assertEqual(scope.read_scope(self.wt), set())

    def test_add_refuses_what_is_not_an_exact_relative_path(self):
        os.symlink(os.path.join(self.main, GUARDED), os.path.join(self.wt, "link.py"))
        for bad in ("core/guard/*", "../t2/install.py", "/etc/passwd", "a/../install.py", "link.py", "", "core/[g]uard/guard.py"):
            out = self.run_cli("add", self.wt, bad)
            self.assertNotEqual(out.returncode, 0, bad)
        self.assertEqual(scope.read_scope(self.wt), set())

    def test_add_refuses_a_folder_that_is_not_a_ticket_worktree(self):
        self.assertNotEqual(self.run_cli("add", self.main, "install.py").returncode, 0)
        self.assertNotEqual(self.run_cli("add", os.path.join(self.base, REPO), "install.py").returncode, 0)

    def test_the_guard_asks_for_add_and_clear_but_not_for_show(self):
        core = guard.load()
        for sub in ("add /w/x install.py", "clear /w/x", "-I add /w/x a"):
            d = guard.decide({"tool": "bash", "command": f"python3 -I {SCOPE} {sub}", "cwd": self.tmp}, core)
            self.assertEqual(d[0], "ask", sub)
        d = guard.decide({"tool": "bash", "command": f"python3 -I {SCOPE} show /w/x", "cwd": self.tmp}, core)
        self.assertEqual(d[0], "allow")


class HookProcess(Base):
    def test_pre_tool_use_asks_and_post_tool_use_grants(self):
        self.add(GUARDED)
        path = os.path.join(self.wt, GUARDED)
        out = self.hook(self.event(path))
        self.assertEqual(out["permissionDecision"], "ask")
        self.assertEqual(scope._granted(self.wt), {})  # a PreToolUse alone grants nothing
        self.assertIsNone(self.hook(self.event(path, kind="PostToolUse")))
        out = self.hook(self.event(path, use="u2"))
        self.assertEqual(out["permissionDecision"], "allow")

    def test_the_decision_is_counted_in_guard_log(self):
        self.add(GUARDED)
        log = os.path.join(self.tmp, "guard.log")
        env = dict(self.env, AI_SETUP_GUARD_LOG=log)
        self.hook(self.event(os.path.join(self.wt, GUARDED)), env=env)
        self.hook(self.event(os.path.join(self.wt, "README.md")), env=env)  # no opinion: no line
        with open(log) as f:
            lines = [l.split("\t")[1:] for l in f.read().splitlines()]
        self.assertEqual(lines, [["edit", "ask", "scoped-edit"]])

    def test_a_tool_without_an_opinion_prints_nothing(self):
        self.assertIsNone(self.hook(self.event(os.path.join(self.main, GUARDED))))

    def test_a_hook_error_asks(self):
        out = self.hook(None, raw="{not json")
        self.assertEqual(out["permissionDecision"], "ask")
        out = self.hook(None, raw="[]")  # valid JSON, wrong shape
        self.assertEqual(out["permissionDecision"], "ask")

    def test_a_crash_while_judging_asks(self):
        event = self.event("core/guard/guard.py")
        event["cwd"] = 5  # a relative path joined to a number: the judge raises
        self.assertEqual(self.hook(event)["permissionDecision"], "ask")

    def test_a_failing_post_hook_is_silent(self):
        out = subprocess.run([sys.executable, "-I", HOOK], input='{"hook_event_name": "PostToolUse", "tool_input": 3}',
                             capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, ""))


class SelfCheck(Base):
    GOOD = {"hooks": {"PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [
        {"type": "command", "command": 'python3 -I "$HOME/.claude/hooks/scoped_edit.py"'}]}],
        "PostToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit", "hooks": [
            {"type": "command", "command": 'python3 -I "$HOME/.claude/hooks/scoped_edit.py"'}]}]}}

    def test_registered_hook_is_no_problem(self):
        self.assertIsNone(scope.hook_problem(self.GOOD))

    def test_missing_hook_is_reported(self):
        self.assertIn("scoped_edit.py", scope.hook_problem({}))
        self.assertIn("scoped_edit.py", scope.hook_problem({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python3 -I "$HOME/.claude/hooks/scoped_edit.py"'}]}]}}))
        self.assertIn("PostToolUse", scope.hook_problem({"hooks": {"PreToolUse": self.GOOD["hooks"]["PreToolUse"]}}))

    def session_start(self, settings):
        os.makedirs(os.path.join(self.tmp, ".claude"), exist_ok=True)
        with open(os.path.join(self.tmp, ".claude", "settings.json"), "w") as f:
            json.dump(settings, f)
        env = dict(self.env, AI_SETUP_SESSIONS_DIR="off", AI_SETUP_PENDING_DIR="off")
        out = subprocess.run([sys.executable, "-I", SESSION_HOOK], input=json.dumps(
            {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": self.tmp}), capture_output=True, text=True,
            env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_session_start_warns_when_the_hook_is_not_registered(self):
        self.assertIn("scoped_edit.py", self.session_start({}))
        self.assertEqual(self.session_start(self.GOOD).strip(), "")


class TicketFlowGate(unittest.TestCase):
    def test_gate_1_writes_the_scope_with_the_helper_and_stops_on_a_missing_path(self):
        with open(os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")) as f:
            text = f.read()
        self.assertIn("{{AI_SETUP}}/core/guard/scope.py add", text)
        self.assertIn("not in the allowlist", text)


if __name__ == "__main__":
    unittest.main()
