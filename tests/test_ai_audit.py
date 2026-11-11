"""Phase 4, learn: ai-audit prints the same 8 practices with a score and evidence, writes nothing in the repo,
lists expired `until` rules, and the cheatsheet documents the cycle. The audit is tested through its CLI only."""
import hashlib, json, os, re, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
AUDIT = os.path.join(ROOT, "core", "skills", "ai-audit", "audit.py")
SKILL = os.path.join(ROOT, "core", "skills", "ai-audit", "SKILL.md")
CHEATSHEET = os.path.join(ROOT, "docs", "cheatsheet.html")

PRACTICES = [
    "Independent review", "Tests tied to intent", "Enforced rules", "Real static checks",
    "Shared knowledge", "Small changes", "CI covers what matters", "Human gate",
]


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def tree_hash(repo):
    """Hash of every file (path + content) in the repo, .git included."""
    digest = hashlib.sha256()
    for base, dirs, files in os.walk(repo):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(base, name)
            digest.update(os.path.relpath(path, repo).encode())
            if not os.path.islink(path):
                with open(path, "rb") as f:
                    digest.update(f.read())
    return digest.hexdigest()


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = os.path.join(self.tmp.name, "sample-repo")
        os.makedirs(self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        self.projects = os.path.join(self.tmp.name, "projects")
        self.dev = os.path.join(self.tmp.name, "dev")

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def commit(self, msg="work"):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def run_audit(self, today="2026-11-10", projects=None, repo=None):
        proc = subprocess.run(
            [sys.executable, "-I", AUDIT, repo or self.repo, "--today", today,
             "--projects-dir", projects or self.projects, "--dev-root", self.dev],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def rows(self, out):
        found = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 4 and parts[0].isdigit():
                found.append(parts)
        return found

    def session(self, name, *lines):
        d = os.path.join(self.projects, "-tmp-" + name.split("/")[0])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name.split("/")[1] + ".jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    # Criterion 1
    def test_1_given_a_repo_when_ai_audit_runs_then_it_prints_8_practices_with_score_and_evidence_and_writes_nothing(self):
        self.write("AGENTS.md", "# A\n\n## Rules\n- E: keep it small. Test: `t`.\n")
        self.write("README.md", "hi\n")
        self.commit()
        before_tree, before_status = tree_hash(self.repo), subprocess.run(
            ["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        out = self.run_audit()
        rows = self.rows(out)
        self.assertEqual([r[1] for r in rows], PRACTICES)
        self.assertEqual([r[0] for r in rows], [str(i) for i in range(1, 9)])
        for _, name, score, evidence in rows:
            self.assertTrue(score == "n/a" or score in "12345", f"{name}: bad score {score!r}")
            self.assertTrue(evidence, f"{name}: empty evidence")
        self.assertEqual(tree_hash(self.repo), before_tree)
        status_after = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(status_after, before_status)
        self.assertFalse(os.path.exists(self.dev), "audit must not create the dev root")

    def test_1b_given_a_dirty_repo_when_ai_audit_runs_then_it_writes_nothing_and_each_evidence_names_its_data(self):
        self.write("AGENTS.md", "## Rules\n- E: a. Test: `t`.\n")
        self.write(".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: pytest\n")
        self.commit()
        self.write("AGENTS.md", "## Rules\n- E: a. Test: `t`.\n- changed\n")  # unstaged edit
        self.write("untracked.txt", "u\n")
        before_tree = tree_hash(self.repo)
        before_status = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        rows = self.rows(self.run_audit())
        self.assertEqual(tree_hash(self.repo), before_tree)
        status_after = subprocess.run(["git", "-C", self.repo, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(status_after, before_status)
        self.assertEqual(sorted(os.listdir(self.repo)), sorted([".git", ".github", "AGENTS.md", "untracked.txt"]))
        # evidence is specific to each practice, not filler
        self.assertIn("session", rows[0][3])
        self.assertIn("criteria", rows[1][3])
        self.assertIn("AGENTS.md", rows[2][3])
        self.assertIn("linters", rows[3][3])
        self.assertIn("decision records", rows[4][3])
        self.assertIn("commits", rows[5][3])
        self.assertIn("ci.yml", rows[6][3])
        self.assertIn("first-parent", rows[7][3])

    def test_1c_given_a_repo_when_ai_audit_runs_then_scores_are_exactly_1_to_5_or_na_and_header_is_printed_once(self):
        self.write("README.md", "x\n")
        self.commit()
        out = self.run_audit()
        for _, name, score, _ in self.rows(out):
            self.assertIn(score, ["1", "2", "3", "4", "5", "n/a"], name)
        self.assertEqual(out.count("# | Practice | Score | Evidence"), 1)

    # Criterion 2
    def test_2_given_an_agents_rule_with_until_2026_10_01_and_today_after_when_ai_audit_runs_then_it_lists_it_as_expired(self):
        self.write("AGENTS.md", "\n".join([
            "# A", "", "## Rules",
            "- Old rule without a test. Why: x. (until 2026-10-01)",
            "- Future rule. Why: y. (until 2027-01-01)",
            "- E: enforced rule. Why: z. Test: `t`.",
            "",
        ]))
        self.commit()
        out = self.run_audit(today="2026-11-10")
        expired = [l for l in out.splitlines() if "expired: test it or delete it" in l]
        self.assertEqual(len(expired), 1, out)
        self.assertIn("AGENTS.md:4", expired[0])
        self.assertIn("Old rule without a test", expired[0])
        self.assertNotIn("Future rule", out.split("expired: test it or delete it")[1])

    def test_2b_same_rule_before_its_date_is_not_expired(self):
        self.write("AGENTS.md", "## Rules\n- Old rule. (until 2026-10-01)\n")
        self.commit()
        self.assertNotIn("expired: test it or delete it", self.run_audit(today="2026-09-30"))

    def test_2e_given_e_rules_and_future_dated_rules_when_ai_audit_runs_then_they_are_not_listed_as_expired(self):
        self.write("AGENTS.md", "\n".join([
            "## Rules",
            "- E: enforced with a stale date. Test: `t`. (until 2020-01-01)",
            "- Future rule. (until 2026-11-11)",
            "- Rule due today. (until 2026-11-10)",
            "- Plain rule without date.",
            "",
        ]))
        self.commit()
        out = self.run_audit(today="2026-11-10")
        self.assertNotIn("expired: test it or delete it", out)
        self.assertIn("0 expired", out)

    def test_2f_given_two_expired_rules_when_ai_audit_runs_then_both_are_listed_with_their_line_and_the_count_is_in_the_evidence(self):
        self.write("AGENTS.md", "\n".join([
            "## Rules",
            "- First old. (until 2026-10-01)",
            "- E: keep.",
            "- Second old. (until 2025-01-31)",
            "",
        ]))
        self.commit()
        out = self.run_audit(today="2026-11-10")
        expired = [l for l in out.splitlines() if "expired: test it or delete it" in l]
        self.assertEqual(len(expired), 2, out)
        self.assertIn("AGENTS.md:2", expired[0])
        self.assertIn("AGENTS.md:4", expired[1])
        self.assertIn("2 expired", out)

    def test_2c_agents_without_rules_section_lists_nothing_and_still_scores(self):
        self.write("AGENTS.md", "# A\n\nJust prose (until 2020-01-01).\n")
        self.commit()
        out = self.run_audit()
        self.assertNotIn("expired: test it or delete it", out)
        self.assertEqual(len(self.rows(out)), 8)

    def test_2d_no_agents_file_still_prints_8_rows(self):
        self.write("README.md", "x\n")
        self.commit()
        self.assertEqual([r[1] for r in self.rows(self.run_audit())], PRACTICES)

    # Extra seams
    def test_review_counts_only_real_sub_review_calls(self):
        self.write("README.md", "x\n")
        self.commit()
        self.session("sample-repo/real", '{"input":{"subagent_type":"sub-review","prompt":"p"}}')
        self.session("sample-repo/mention", '{"text":"we should use sub-review at some point"}')
        row = self.rows(self.run_audit())[0]
        self.assertIn("1 of 2 sessions", row[3])
        self.assertNotEqual(row[2], "n/a")

    def test_missing_sessions_dir_is_na_and_exit_0(self):
        self.write("README.md", "x\n")
        self.commit()
        row = self.rows(self.run_audit(projects=os.path.join(self.tmp.name, "nope")))[0]
        self.assertEqual(row[2], "n/a")
        self.assertTrue(row[3])

    def test_not_a_git_repo_gives_na_for_git_rows_without_crashing(self):
        plain = os.path.join(self.tmp.name, "plain")
        os.makedirs(plain)
        proc = subprocess.run([sys.executable, "-I", AUDIT, plain, "--projects-dir", self.projects, "--dev-root", self.dev],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self.rows(proc.stdout)
        self.assertEqual([r[1] for r in rows], PRACTICES)
        self.assertEqual(rows[5][2], "n/a")
        self.assertEqual(rows[7][2], "n/a")

    def test_big_commit_and_ci_and_decisions_show_in_scores(self):
        self.write("AGENTS.md", "## Rules\n- E: a. Test: `t`.\n")
        self.write("docs/decisions/000-template.md", "t\n")
        self.write("docs/decisions/001-a.md", "a\n")
        self.write("docs/decisions/002-b.md", "b\n")
        self.write("docs/decisions/003-c.md", "c\n")
        self.write(".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: pytest\n  e2e:\n    steps:\n      - run: playwright test\n")
        self.write("big.txt", "line\n" * 500)
        self.commit("big")
        rows = self.rows(self.run_audit())
        self.assertIn("1 of 1 commits above 400", rows[5][3])
        self.assertLess(int(rows[5][2]), 5)
        self.assertEqual(rows[4][2], "5")
        self.assertEqual(rows[6][2], "5")


    # Review findings on PR 3
    def test_tslint_installed_and_configured_is_not_a_missing_tool(self):
        self.write("package.json", '{"devDependencies": {"tslint": "^6.0.0"}}\n')
        self.write("tslint.json", "{}\n")
        self.write("src/a.ts", "// tslint:disable-next-line\nconst a = 1;\n")
        self.commit()
        row = self.rows(self.run_audit())[3]
        self.assertIn("missing tool: 0", row[3])
        self.assertEqual(row[2], "5")

    def test_linter_declared_in_a_monorepo_package_counts_as_installed(self):
        self.write(".eslintrc.json", "{}\n")
        self.write("packages/web/package.json", '{"devDependencies": {"eslint": "^9.0.0"}}\n')
        self.write("packages/web/src/a.js", "/* eslint-disable no-console */\nconsole.log(1)\n")
        self.commit()
        row = self.rows(self.run_audit())[3]
        self.assertIn("missing tool: 0", row[3])
        self.assertEqual(row[2], "5")

    def test_session_folder_matches_the_repo_name_as_a_whole_word_not_a_substring(self):
        self.write("README.md", "x\n")
        self.commit()
        self.session("xsample-repo/other", '{"input":{"subagent_type":"sub-review"}}')
        row = self.rows(self.run_audit())[0]
        self.assertEqual(row[2], "n/a")

    def test_a_worktree_finds_the_sessions_of_the_main_repo_name(self):
        self.write("README.md", "x\n")
        self.commit()
        wt = os.path.join(self.tmp.name, "feature-wt")
        git(self.repo, "worktree", "add", "-q", wt, "-b", "feature")
        self.session("sample-repo/main", '{"input":{"subagent_type":"sub-review"}}')
        row = self.rows(self.run_audit(repo=wt))[0]
        self.assertIn("1 of 1 sessions", row[3])

    def test_a_session_log_with_bad_bytes_is_still_counted(self):
        self.write("README.md", "x\n")
        self.commit()
        d = os.path.join(self.projects, "-tmp-sample-repo")
        os.makedirs(d)
        with open(os.path.join(d, "bad.jsonl"), "wb") as f:
            f.write(b'\xff\xfe{"input":{"subagent_type":"sub-review"}}\n')
        row = self.rows(self.run_audit())[0]
        self.assertIn("1 of 1 sessions", row[3])

    def test_a_malformed_until_date_is_reported_not_silently_ignored(self):
        self.write("AGENTS.md", "## Rules\n- Keep it small (until 2026-13-45)\n- Other (until 2026-1-5)\n- Old (until 2020-01-01)\n")
        self.commit()
        out = self.run_audit()
        self.assertIn("invalid date: AGENTS.md:2:", out)
        self.assertIn("invalid date: AGENTS.md:3:", out)
        self.assertEqual(out.count("expired: test it or delete it"), 1)
        self.assertIn("2 invalid dates", self.rows(out)[2][3])


class CheatsheetCycle(unittest.TestCase):
    def setUp(self):
        with open(CHEATSHEET, encoding="utf-8") as f:
            text = f.read()
        match = re.search(r'<section class="blk" id="cycle">(.*?)</section>', text, re.S)
        self.assertIsNotNone(match, 'cheatsheet needs <section id="cycle">')
        self.text = text
        self.section = match.group(1)

    # Criterion 3
    def test_3_given_the_cheatsheet_when_this_phase_lands_then_it_has_one_section_on_the_cycle_with_6_steps_and_what_covers_each(self):
        self.assertEqual(self.text.count('id="cycle"'), 1)
        self.assertIn('href="#cycle"', self.text)
        for lang in ("es", "en"):
            spans = re.findall(rf'<span data-l="{lang}">(.*?)</span>', self.section, re.S)
            body = " ".join(spans)
            self.assertTrue(body, f"no {lang} text in the cycle section")
        for step in ("decide", "guardrails", "build", "independent review", "human gate", "learn"):
            self.assertIn(step, self.section.lower(), f"missing step: {step}")
        for covers in ("grillme", "criteria.md", "repo-guardrails", "ticket-flow", "sub-builder", "sub-tester",
                       "sub-review", "Gate 2", "meta-setup", "ai-audit"):
            self.assertIn(covers, self.section, f"missing: {covers}")
        for step_es in ("decidir", "revisión independiente", "puerta humana", "aprender"):
            self.assertIn(step_es, self.section.lower(), f"missing es step: {step_es}")
        self.assertIn("El ciclo", self.section)
        self.assertIn("The cycle", self.section)

    def test_3b_the_cycle_section_has_6_numbered_steps_each_with_es_and_en_text_and_its_own_skill_or_gate(self):
        rows = re.findall(r"<tr><td>(\d)</td>(.*?)</tr>", self.section, re.S)
        self.assertEqual([r[0] for r in rows], ["1", "2", "3", "4", "5", "6"])
        expect = [("Decidir", "Decide", "grillme"), ("Guardrails", "Guardrails", "repo-guardrails"),
                  ("Construir", "Build", "ticket-flow"), ("Revisión independiente", "Independent review", "sub-review"),
                  ("Puerta humana", "Human gate", "Gate 2"), ("Aprender", "Learn", "ai-audit")]
        for (num, body), (es, en, covers) in zip(rows, expect):
            self.assertIn(f'<span data-l="es">{es}</span>', body, f"step {num} es")
            self.assertIn(f'<span data-l="en">{en}</span>', body, f"step {num} en")
            self.assertIn(covers, body, f"step {num} covered by")
            cells = re.findall(r"<td>(.*?)</td>", body, re.S)
            for lang in ("es", "en"):
                self.assertTrue(re.search(rf'<span data-l="{lang}">[^<]*\S', cells[-1]), f"step {num} {lang} coverage text")

    def test_ai_audit_has_a_row_in_the_skills_reference_in_both_languages(self):
        row = re.search(r"<tr><td><code>ai-audit</code></td>(.*?)</tr>", self.text, re.S)
        self.assertIsNotNone(row, "skills reference needs an ai-audit row")
        self.assertIn('data-l="es"', row.group(1))
        self.assertIn('data-l="en"', row.group(1))


class SkillDoc(unittest.TestCase):
    def test_skill_names_only_real_flags_and_says_scores_are_heuristics(self):
        with open(SKILL, encoding="utf-8") as f:
            text = f.read()
        with open(AUDIT, encoding="utf-8") as f:
            code = f.read()
        for flag in set(re.findall(r"`(--[a-z-]+)", text)):
            self.assertIn(flag, code, f"SKILL.md names {flag} but audit.py lacks it")
        self.assertIn("heuristic", text.lower())
        self.assertIn("python3 -I {{AI_SETUP}}/core/skills/ai-audit/audit.py", text)


if __name__ == "__main__":
    unittest.main()
