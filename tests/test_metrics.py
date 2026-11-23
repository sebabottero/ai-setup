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

    def test_commits_come_from_git_log_of_the_repo(self):
        repo = os.path.join(self.dev, "repos", "r")
        os.makedirs(repo)
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-11-18T10:00:00", GIT_COMMITTER_DATE="2026-11-18T10:00:00",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for cmd in (["init", "-q", "-b", "a"], ["commit", "-q", "--allow-empty", "-m", "x"]):
            subprocess.run(["git", "-C", repo, *cmd], check=True, env=env, capture_output=True)
        self.log("reviews.log", [review(18, 9, "a", 1, 3, "PASS", "nit=1")])
        self.assertIn("a 1", self.build())

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

    def test_outside_sandbox_section_is_an_empty_marked_hook(self):
        out = self.build()
        self.assertIn("## Outside-sandbox commands", out)
        self.assertIn("criterion 15", out)

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
