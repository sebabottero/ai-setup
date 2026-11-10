"""repo-guardrails templates: every file the skill names exists, AGENTS.md carries risk tiers and the rule
convention, and the CI diff-size step warns (never fails) on a PR above 400 changed lines."""
import os, re, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SKILL_DIR = os.path.join(ROOT, "core", "skills", "repo-guardrails")
TEMPLATES = os.path.join(SKILL_DIR, "templates")
EXPECTED = {
    "AGENTS.md",
    "CLAUDE.md",
    "decisions/000-template.md",  # copied to docs/decisions/ in the target repo
    ".github/pull_request_template.md",
    "ci-github-actions.yml",
}


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def section(text, heading):
    """Body of a `## heading` section, up to the next `## `."""
    match = re.search(rf"^## {re.escape(heading)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1) if match else None


class SkillNamesTemplates(unittest.TestCase):
    def test_every_template_named_in_skill_exists(self):
        named = set(re.findall(r"templates/([\w./-]+[\w])", read(SKILL_DIR, "SKILL.md")))
        self.assertTrue(EXPECTED <= named, f"SKILL.md does not name: {sorted(EXPECTED - named)}")
        missing = sorted(p for p in named if not os.path.isfile(os.path.join(TEMPLATES, p)))
        self.assertEqual(missing, [], "SKILL.md names template files that do not exist")

    def test_receipt_lists_every_generated_file(self):
        receipt = section(read(SKILL_DIR, "SKILL.md"), "Receipt")
        self.assertIsNotNone(receipt, "SKILL.md needs a '## Receipt' section")
        for out in ("AGENTS.md", "CLAUDE.md", "docs/decisions/000-template.md",
                    ".github/pull_request_template.md", ".github/workflows/"):
            self.assertIn(out, receipt)


class AgentsTemplate(unittest.TestCase):
    def setUp(self):
        self.text = read(TEMPLATES, "AGENTS.md")

    def test_risk_tiers_table_has_three_rows(self):
        body = section(self.text, "Risk tiers")
        self.assertIsNotNone(body, "AGENTS.md template needs a '## Risk tiers' section")
        rows = [l for l in body.splitlines() if l.startswith("|") and not re.match(r"^\|[\s|:-]+\|$", l)][1:]
        self.assertEqual(len(rows), 3, rows)
        for row, tier in zip(rows, ("low", "medium", "high")):
            self.assertIn(tier, row.lower())

    def test_rule_convention_is_enforced_or_dated(self):
        rules = section(self.text, "Rules")
        self.assertIsNotNone(rules, "AGENTS.md template needs a '## Rules' section")
        self.assertRegex(rules, r"(?m)^- E: ")
        self.assertRegex(rules, r"(?m)^- .*\(until YYYY-MM-DD\)$")


class OtherTemplates(unittest.TestCase):
    def test_decision_template_is_short_and_complete(self):
        text = read(TEMPLATES, "decisions", "000-template.md")
        for field in ("Context", "Decision", "Why", "Alternatives considered", "Date"):
            self.assertIn(field, text)
        self.assertLessEqual(len(text.splitlines()), 22)

    def test_pr_template_asks_for_criteria_tests_review_and_risk(self):
        text = read(TEMPLATES, ".github", "pull_request_template.md")
        for field in ("Criteria", "criteria.md", "Tests", "Reviewer report", "Risk tier"):
            self.assertIn(field, text)


class CiDiffSize(unittest.TestCase):
    """Runs the diff-size step's own script (between its markers) in a throwaway git repo."""

    def setUp(self):
        text = read(TEMPLATES, "ci-github-actions.yml")
        match = re.search(r"# diff-size:begin\n(.*?)\n\s*# diff-size:end", text, re.S)
        self.assertIsNotNone(match, "ci template needs the diff-size step between its markers")
        self.script = "\n".join(l.strip() for l in match.group(1).splitlines())
        self.assertIn("e2e", text, "ci template needs the optional (commented) e2e job")

    def test_missing_base_is_reported_not_failed(self):
        result = self.run_with(401, base="origin/nope")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::notice::", result.stdout)
        self.assertNotIn("::warning::", result.stdout)

    def run_with(self, lines, base="main"):
        with tempfile.TemporaryDirectory() as repo:
            def git(*args):
                subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                                "-c", "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True)
            git("init", "-q", "-b", "main")
            git("commit", "-q", "--allow-empty", "-m", "base")
            git("checkout", "-q", "-b", "feature")
            with open(os.path.join(repo, "big.txt"), "w") as f:
                f.write("".join(f"line {i}\n" for i in range(lines)))
            git("add", "big.txt")
            git("commit", "-q", "-m", "change")
            return subprocess.run(["bash", "-c", self.script], cwd=repo, capture_output=True, text=True,
                                  env={**os.environ, "BASE": base})

    def test_big_pr_warns_without_failing(self):
        result = self.run_with(401)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning::", result.stdout)
        self.assertIn("401", result.stdout)

    def test_small_pr_is_silent(self):
        result = self.run_with(10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("::warning::", result.stdout)


if __name__ == "__main__":
    unittest.main()
