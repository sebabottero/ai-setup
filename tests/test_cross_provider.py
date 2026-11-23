"""Cross-provider review (criterion 9): off by default, offered at Gate 1 only for a high-tier ticket, a second reviewer
from another provider reads the same diff read-only, and its report sits beside the main one (both kept).
Prompt wording is checked as text; `review_report.py header --reviewer`, run_json and ai-audit are tested for real."""
import json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
XPROV = os.path.join(ROOT, "core", "agents", "sub-review-xprov.md")
REPORT = os.path.join(ROOT, "core", "guard", "review_report.py")
RUN_JSON = os.path.join(ROOT, "core", "guard", "run_json.py")


def flat(path):
    with open(path, encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).lower()


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class Wording(unittest.TestCase):
    def assert_in(self, path, *needles):
        text = flat(path)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{os.path.basename(path)} lacks: {needle}")

    def test_9_default_off_and_only_for_the_high_tier_at_gate_1(self):
        self.assert_in(
            TICKET_FLOW, "cross-provider review (opt-in, high tier only)", "only when it is **high**, gate 1 carries one more line",
            "any other tier, or no tier: no line, no question", "the default is off", "silence or a plain ok means off",
            "--cross-review on|off",
        )

    def test_9_second_reviewer_is_another_provider_on_the_same_diff(self):
        self.assert_in(
            TICKET_FLOW, "codex or opencode with a non-claude model", "the same range, plan or `criteria.md` as `sub-review`",
            "codex exec --sandbox read-only", "opencode run --agent sub-review-xprov --model <non-claude provider/model>",
        )

    def test_9_second_reviewer_is_read_only(self):
        self.assert_in(TICKET_FLOW, "it is read-only: it edits nothing and writes no file")
        self.assert_in(XPROV, "edit: none", "bash: read-only", "read only, with no exception", "never edit, create or delete any file")
        self.assertNotIn("Write", re.search(r"claude_tools: (.*)", open(XPROV).read()).group(1))

    def test_9_report_goes_to_a_separate_path_and_both_are_kept(self):
        self.assert_in(
            TICKET_FLOW, "<branch>.<provider>.md", "the merge gate's `<branch>.md` is not touched",
            "`sub-review`'s report and the second one are both kept", "--reviewer <provider>",
        )

    def test_9_same_findings_table_as_sub_review(self):
        self.assert_in(XPROV, "`| severity | triage | reason | file:line | problem | fix |`", "`blocking`", "`fix_now`", "`defer`", "`reject`")

    def test_9_no_policy_change_is_asked_for(self):
        self.assert_in(TICKET_FLOW, "each one asks for my ok like any other command; nothing here widens the policy")


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "proj")
        self.dev = os.path.join(self.tmp.name, "dev")
        os.makedirs(self.repo)
        for cmd in (["init", "-q", "-b", "ai/t-1"], ["config", "user.email", "a@b"], ["config", "user.name", "a"]):
            sh("git", *cmd, cwd=self.repo)
        open(os.path.join(self.repo, "f"), "w").write("x\n")
        sh("git", "add", "f", cwd=self.repo)
        sh("git", "commit", "-qm", "c", cwd=self.repo)
        self.reports = os.path.join(self.dev, "reviews", "proj", "ai")

    def header(self, *extra):
        run = sh(sys.executable, "-I", REPORT, "header", "--dir", self.repo, "--dev-root", self.dev, *extra)
        return run

    def write(self, name, text):
        os.makedirs(self.reports, exist_ok=True)
        with open(os.path.join(self.reports, name), "w") as f:
            f.write(text)


class ReviewerOption(Repo):
    def test_reviewer_path_is_branch_dot_provider_and_header_names_it(self):
        run = self.header("--reviewer", "codex", "--verdict", "PASS")
        self.assertEqual(run.returncode, 0, run.stderr)
        lines = run.stdout.splitlines()
        self.assertEqual(lines[0], os.path.join(self.dev, "reviews", "proj", "ai", "t-1.codex.md"))
        self.assertIn("Reviewer: codex", lines)
        self.assertIn("Verdict: PASS", lines)
        self.assertTrue(any(l.startswith("Commit: ") and len(l) > 10 for l in lines))

    def test_reviewer_header_keeps_both_reports_and_archives_nothing(self):
        self.write("t-1.md", "Verdict: PASS\nmain report\n")
        self.write("t-1.codex.md", "Verdict: FAIL\nold codex report\n")
        self.header("--reviewer", "codex")
        self.assertEqual(sorted(os.listdir(self.reports)), ["t-1.codex.md", "t-1.md"])
        self.assertEqual(open(os.path.join(self.reports, "t-1.md")).read(), "Verdict: PASS\nmain report\n")

    def test_main_header_ignores_the_extra_report_and_still_archives_its_own(self):
        self.write("t-1.md", "Verdict: PASS\nmain report\n")
        self.write("t-1.codex.md", "Verdict: FAIL\ncodex\n")
        run = self.header()
        self.assertEqual(run.stdout.splitlines()[0], os.path.join(self.reports, "t-1.md"))
        self.assertIn("Reviewer: sub-review", run.stdout)
        self.assertEqual(sorted(os.listdir(self.reports)), ["t-1.codex.md", "t-1.md", "t-1.r1.md"])

    def test_bad_reviewer_names_are_refused(self):
        for bad in ("r2", "../x", "Codex Two", "a.b", ""):
            if not bad:
                continue
            run = self.header("--reviewer", bad)
            self.assertNotEqual(run.returncode, 0, bad)
        self.assertFalse(os.path.exists(self.reports))

    def test_reviewer_only_applies_to_header(self):
        run = sh(sys.executable, "-I", REPORT, "rounds", "--stage", "3", "--dir", self.repo, "--dev-root", self.dev, "--reviewer", "codex")
        self.assertNotEqual(run.returncode, 0)


class AuditDoesNotDoubleCount(Repo):
    def test_extra_report_is_not_counted_as_a_branch_report(self):
        self.write("t-1.md", "Reviewer: sub-review\nVerdict: PASS\n")
        self.write("t-1.r1.md", "Reviewer: sub-review\n")
        self.write("t-1.codex.md", "Reviewer: codex\nVerdict: PASS\n")
        sys.path.insert(0, os.path.join(ROOT, "core", "skills", "ai-audit"))
        try:
            import audit
        finally:
            sys.path.pop(0)
        ctx = {"names": ["proj"], "projects_dir": os.path.join(self.tmp.name, "none"), "dev_root": self.dev}
        _, detail = audit.review(ctx)
        self.assertIn("1 review reports", detail)
        self.assertIn("(+1 earlier rounds)", detail)
        self.assertIn("(+1 cross-provider)", detail)

    def test_a_branch_whose_name_has_a_dot_is_still_a_branch(self):
        self.write("v1.2.md", "Reviewer: sub-review\nVerdict: PASS\n")
        self.write("plain.md", "no header at all\n")
        sys.path.insert(0, os.path.join(ROOT, "core", "skills", "ai-audit"))
        try:
            import audit
        finally:
            sys.path.pop(0)
        ctx = {"names": ["proj"], "projects_dir": os.path.join(self.tmp.name, "none"), "dev_root": self.dev}
        _, detail = audit.review(ctx)
        self.assertIn("2 review reports", detail)
        self.assertNotIn("cross-provider", detail)


class RunJson(unittest.TestCase):
    def test_cross_review_is_off_by_default_and_records_the_choice(self):
        with tempfile.TemporaryDirectory() as dev:
            sh(sys.executable, "-I", RUN_JSON, "update", "T-9", "--dev-root", dev, "--branch", "ai/t-9")
            path = os.path.join(dev, "handoffs", "T-9", "run.json")
            self.assertEqual(json.load(open(path))["cross_review"], "off")
            sh(sys.executable, "-I", RUN_JSON, "update", "T-9", "--dev-root", dev, "--cross-review", "on")
            self.assertEqual(json.load(open(path))["cross_review"], "on")
            sh(sys.executable, "-I", RUN_JSON, "update", "T-9", "--dev-root", dev, "--pr", "3")
            self.assertEqual(json.load(open(path))["cross_review"], "on")  # a later call does not reset it
            self.assertNotEqual(sh(sys.executable, "-I", RUN_JSON, "update", "T-9", "--dev-root", dev, "--cross-review", "maybe").returncode, 0)


if __name__ == "__main__":
    unittest.main()
