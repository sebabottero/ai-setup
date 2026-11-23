import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "core", "scripts", "metrics.py")
sys.path.insert(0, os.path.join(ROOT, "core", "scripts"))
import metrics

TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    TMP.cleanup()


def review(day, hour, branch, rnd, stage, verdict, found, triage=None, repo="r"):
    f = [f"2026-11-{day:02d}T{hour:02d}:00:00", repo, branch, str(rnd), str(stage), verdict, found]
    return "\t".join(f + ([triage] if triage else []))


def action(day, session, what, cmd, hour=10):
    return f"2026-11-{day:02d}T{hour:02d}:00:00\t{session}\tMEDIUM\t{what}\tgit push *\t{cmd}"


class Metrics(unittest.TestCase):
    def setUp(self):
        self.dev = tempfile.mkdtemp(dir=TMP.name)
        self.projects = tempfile.mkdtemp(dir=TMP.name)
        os.makedirs(os.path.join(self.dev, "logs"))

    def log(self, name, lines):
        with open(os.path.join(self.dev, "logs", name), "w") as f:
            f.write("\n".join(lines) + "\n")

    def read(self, name):
        with open(os.path.join(self.dev, "logs", name)) as f:
            return f.read()

    def run_json(self, slug, run):
        os.makedirs(os.path.join(self.dev, "handoffs", slug))
        with open(os.path.join(self.dev, "handoffs", slug, "run.json"), "w") as f:
            json.dump(run, f)

    def build(self, week="2026-W47"):
        return metrics.build(self.dev, week, projects=self.projects, guard_path=os.path.join(self.dev, "none.log"),
                             actions_path=os.path.join(self.dev, "logs", "actions.log"),
                             reviews_path=os.path.join(self.dev, "logs", "reviews.log"))

    def test_week_bounds_and_default(self):
        self.assertEqual(metrics.week_bounds("2026-W47")[0].isoformat(), "2026-11-16T00:00:00")
        self.assertEqual(metrics.current_week(__import__("datetime").datetime(2026, 11, 20)), "2026-W47")
        with self.assertRaises(ValueError):
            metrics.week_bounds("47")

    def test_rounds_to_pass_counts_up_to_the_first_pass_across_weeks(self):
        self.log("reviews.log", [review(12, 9, "a", 1, 3, "NEEDS CHANGES", "major=1"),   # previous week
                                 review(17, 9, "a", 2, 3, "NEEDS CHANGES", "major=1"),
                                 review(18, 9, "a", 3, 3, "PASS", "nit=1"),
                                 review(19, 9, "b", 1, 3, "NEEDS CHANGES", "blocking=1"),
                                 review(19, 9, "b", 1, 3, "NEEDS CHANGES", "blocking=1")])  # same round logged twice
        out = self.build()
        self.assertIn("| r | a | 3 | 3 | PASS |", out)
        self.assertIn("| r | b | 3 | 1 | not PASS yet |", out)

    def git_repo(self, name="r"):
        repo = os.path.join(self.dev, "repos", name)
        os.makedirs(repo)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-11-18T10:00:00", GIT_COMMITTER_DATE="2026-11-18T10:00:00",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def git(*cmd):
            subprocess.run(["git", "-C", repo, *cmd], check=True, env=env, capture_output=True)
        git("init", "-q", "-b", "main")
        return git

    def test_commits_are_the_branchs_own_not_the_history_it_sits_on(self):
        git = self.git_repo()
        for _ in range(3):
            git("commit", "-q", "--allow-empty", "-m", "main")
        git("checkout", "-q", "-b", "a")
        for _ in range(2):
            git("commit", "-q", "--allow-empty", "-m", "own")
        self.log("reviews.log", [review(18, 9, "a", 1, 3, "PASS", "nit=1")])
        self.assertIn("a 2", self.build())

    def test_commits_are_n_a_when_there_is_no_base_ref(self):
        git = self.git_repo()
        git("checkout", "-q", "-b", "a")
        git("commit", "-q", "--allow-empty", "-m", "x")
        git("branch", "-q", "-M", "other")  # the only branch: no main, no origin/main to compare with
        self.log("reviews.log", [review(18, 9, "other", 1, 3, "PASS", "nit=1")])
        self.assertIn("other n/a", self.build())

    def test_ask_answers_use_the_ask_time_for_a_declined_line_stamped_later(self):
        self.log("actions.log", [action(18, "s1", "asked", "git push a"), action(18, "s1", "approved", "git push a"),
                                 action(22, "s1", "asked", "git push b"), action(24, "s1", "declined", "git push b"),  # next week stamp
                                 action(12, "s2", "asked", "git push z"), action(12, "s2", "approved", "git push z")])
        out = self.build()
        self.assertIn("Asks in the action log: 2 | approved 1 | declined 1 | unknown 0 | unresolved 0 | approval rate 50%", out)

    def test_runs_per_ticket_only_those_active_in_the_week(self):
        self.run_json("t-in", {"ticket": "t-in", "sessions": ["x", "y"], "branch": "ai/in", "pr": 7,
                               "rounds": [{"stage": 3}], "start": "2026-11-17T09:00:00", "end": None})
        self.run_json("t-old", {"ticket": "t-old", "sessions": [], "start": "2026-10-01T09:00:00", "end": "2026-10-02T09:00:00"})
        out = self.build()
        self.assertIn("| t-in | ai/in | 7 | 2 | 1 | 2026-11-17T09:00:00 | open |", out)
        self.assertNotIn("t-old", out)

    def test_tokens_and_time_per_ticket_and_unknown_when_not_recorded(self):
        d = os.path.join(self.projects, "p")
        os.makedirs(d)
        with open(os.path.join(d, "s1.jsonl"), "w") as f:
            for ts, o in (("2026-11-18T10:00:00Z", 10), ("2026-11-18T10:20:00Z", 20)):
                f.write(json.dumps({"type": "assistant", "timestamp": ts, "message": {
                    "model": "m", "usage": {"input_tokens": 100, "output_tokens": o}}}) + "\n")
        self.run_json("t1", {"ticket": "t1", "sessions": ["s1", "gone"], "start": "2026-11-18T09:00:00"})
        self.run_json("t2", {"ticket": "t2", "sessions": [], "start": "2026-11-18T09:00:00"})
        out = self.build()
        self.assertIn("| t1 | 1 of 2 (no transcript: gone) | 230 | 2 | 20m |", out)
        self.assertIn("| t2 | none (no session ids in run.json) | unknown | unknown | unknown |", out)

    def test_findings_by_severity_and_triage_new_and_old_formats(self):
        self.log("reviews.log", [review(17, 9, "a", 1, 3, "NEEDS CHANGES", "warning=2 nit=5"),            # old, 7 fields
                                 review(18, 9, "a", 2, 3, "PASS", "minor=2 nit=1", "defer=2 reject=1"),
                                 review(19, 9, "b", 1, 4, "PASS", "none", "none"),
                                 review(10, 9, "c", 1, 3, "PASS", "major=9")])                           # other week
        out = self.build()
        self.assertIn("Severity: nit 6, warning 2, minor 2", out)
        self.assertIn("Triage: defer 2, reject 1", out)
        self.assertNotIn("major 9", out)

    def test_tz_aware_non_string_and_garbage_run_json_do_not_crash_and_are_counted_as_skipped(self):
        self.run_json("aware", {"ticket": "aware", "sessions": [], "branch": "ai/z", "start": "2026-11-18T09:00:00+00:00",
                                "end": "2026-11-18T11:00:00Z"})
        self.run_json("num", {"ticket": "num", "start": 1763460000})
        self.run_json("listy", {"ticket": "listy", "start": "2026-11-18T09:00:00", "sessions": "abc", "rounds": 5})
        os.makedirs(os.path.join(self.dev, "handoffs", "junk"))
        with open(os.path.join(self.dev, "handoffs", "junk", "run.json"), "w") as f:
            f.write("[1, 2")
        out = self.build()
        self.assertIn("| aware | ai/z |", out)
        self.assertIn("| listy |", out)
        self.assertIn("Skipped 2 run.json files", out)  # num (start is not a string) and junk (not a JSON object)

    def test_tz_aware_review_line_does_not_crash(self):
        self.log("reviews.log", ["2026-11-18T10:00:00+00:00\tr\ta\t1\t3\tPASS\tnit=1"])
        self.assertIn("| r | a | 3 | 1 | PASS |", self.build())

    def test_hostile_review_line_cannot_make_git_write_a_file_or_leave_repos(self):
        repo = os.path.join(self.dev, "repos", "r")
        os.makedirs(repo)
        subprocess.run(["git", "-C", repo, "init", "-q"], check=True, capture_output=True)
        target = os.path.join(self.dev, "pwned.txt")
        self.log("reviews.log", [review(18, 9, "--output=" + target, 1, 3, "PASS", "nit=1"),
                                 review(18, 9, "a", 1, 3, "PASS", "nit=1", repo="../../etc"),
                                 review(18, 9, "a", 1, 3, "PASS", "nit=1", repo="/etc"),
                                 review(18, 9, "a\x01b", 1, 3, "PASS", "nit=1")])
        out = self.build()
        self.assertFalse(os.path.exists(target))
        self.assertIn("--output=" + target + " n/a", out)
        self.assertIsNone(metrics.git_commits(os.path.join(self.dev, "repos"), "../../etc", "a", *metrics.week_bounds("2026-W47")))
        self.assertIsNone(metrics.git_commits(os.path.join(self.dev, "repos"), "/etc", "a", *metrics.week_bounds("2026-W47")))

    def test_a_symlinked_output_file_is_refused(self):
        victim = os.path.join(self.dev, "victim.txt")
        with open(victim, "w") as f:
            f.write("keep")
        os.symlink(victim, os.path.join(self.dev, "logs", "metrics-2026-W47.md"))
        env = dict(os.environ, AI_SETUP_GUARD_LOG="off", AI_SETUP_PROJECTS_DIR=self.projects)
        run = subprocess.run([sys.executable, "-I", SCRIPT, "--week", "2026-W47", "--dev-root", self.dev],
                             capture_output=True, text=True, env=env)
        self.assertNotEqual(run.returncode, 0)
        with open(victim) as f:
            self.assertEqual(f.read(), "keep")

    def outside(self, day, cmd, what="ran", rule="outside-sandbox", risk="MEDIUM", hour=10):
        return f"2026-11-{day:02d}T{hour:02d}:00:00\ts1\t{risk}\t{what}\t{rule}\t{cmd}"

    def section(self, out):
        return out.split("## Outside-sandbox commands")[1]

    def test_outside_sandbox_groups_by_head_after_env_cd_and_path_prefixes(self):
        self.log("actions.log", [
            self.outside(17, "ls"), self.outside(17, "ls -la"),
            self.outside(18, "FOO=1 BAR=2 ls x"),
            self.outside(18, "cd ~/Dev/x && /usr/bin/ls"),
            self.outside(19, "cd /a; export JAVA_HOME=/b && ./gradlew build"),
            self.outside(19, "git fetch origin | tail -2"),
            self.outside(19, "S=/*** python3 - <<'EOF'"),
        ])
        sec = self.section(self.build())
        self.assertIn("| ls | 4 |", sec)
        self.assertIn("| gradlew | 1 |", sec)
        self.assertIn("| git | 1 |", sec)
        self.assertIn("| python3 | 1 |", sec)
        self.assertIn("Total: 7", sec)
        self.assertLess(sec.index("| ls | 4 |"), sec.index("| git | 1 |"))
        self.assertLess(sec.index("| git | 1 |"), sec.index("| gradlew | 1 |"))

    def test_outside_sandbox_counts_only_ran_medium_rule_lines_in_the_week(self):
        self.log("actions.log", [
            self.outside(16, "ls", hour=0),            # Monday 00:00: in
            self.outside(22, "ls", hour=23),           # Sunday: in
            self.outside(15, "ls", hour=23),           # previous week
            self.outside(23, "ls", hour=0),            # next week
            self.outside(18, "ls", what="asked"), self.outside(18, "ls", what="deny"),
            self.outside(18, "ls", what="approved"),
            self.outside(18, "ls", rule="git push *"), self.outside(18, "ls", risk="HIGH"),
            "garbage line", self.outside(18, "ls") + "\textra",
        ])
        sec = self.section(self.build())
        self.assertIn("| ls | 2 |", sec)
        self.assertIn("Total: 2", sec)

    def test_outside_sandbox_empty_week_and_missing_log_print_none(self):
        self.log("actions.log", [self.outside(9, "ls")])
        self.assertIn("none", self.section(self.build()))
        os.remove(os.path.join(self.dev, "logs", "actions.log"))
        self.assertIn("none", self.section(self.build()))

    def test_outside_sandbox_top_n_and_other_and_redacted_text_untouched(self):
        self.log("actions.log", [self.outside(17, f"cmd{i:02d} S=/***") for i in range(20)] + [self.outside(17, "cmd00")])
        sec = self.section(self.build())
        self.assertIn("| cmd00 | 2 |", sec)
        self.assertIn("| cmd14 | 1 |", sec)
        self.assertNotIn("cmd15", sec)
        self.assertIn("| other (5 commands) | 5 |", sec)
        self.assertIn("Total: 21", sec)
        self.assertNotIn("/***", sec)

    def test_outside_sandbox_unparseable_command_is_named_not_dropped(self):
        self.log("actions.log", [self.outside(17, "cd /x &&"), self.outside(17, "FOO=1")])
        sec = self.section(self.build())
        self.assertIn("| (no command word) | 2 |", sec)

    def test_cli_writes_only_the_metrics_file_and_leaves_logs_untouched(self):
        lines = [review(18, 9, "a", 1, 3, "PASS", "nit=1")]
        self.log("reviews.log", lines)
        self.log("actions.log", [action(18, "s1", "asked", "git push a")])
        before = {n: self.read(n) for n in os.listdir(os.path.join(self.dev, "logs"))}
        env = dict(os.environ, AI_SETUP_GUARD_LOG="off", AI_SETUP_PROJECTS_DIR=self.projects)
        env.pop("AI_SETUP_ACTIONS_LOG", None)
        run = subprocess.run([sys.executable, "-I", SCRIPT, "--week", "2026-W47", "--dev-root", self.dev],
                             capture_output=True, text=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        path = os.path.join(self.dev, "logs", "metrics-2026-W47.md")
        self.assertEqual(run.stdout.strip(), path)
        self.assertTrue(os.path.exists(path))
        for n, text in before.items():
            self.assertEqual(self.read(n), text)
        self.assertEqual(sorted(os.listdir(os.path.join(self.dev, "logs"))), sorted(list(before) + ["metrics-2026-W47.md"]))


if __name__ == "__main__":
    unittest.main()
