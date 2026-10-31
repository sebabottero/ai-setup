import json, os, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude", "hooks"))
sys.path.insert(0, os.path.join(ROOT, "adapters", "claude"))
import tune_notice, tune_stats

DAY = 86400


def make(folder, sid, frict=0, msgs=10, agent=0, mtime=None):
    for sub, data in (("facets", {"friction_counts": {"wrong_approach": frict} if frict else {}, "session_type": "multi_task"}),
                      ("session-meta", {"user_message_count": msgs, "tool_counts": {"Agent": agent} if agent else {}})):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
        path = os.path.join(folder, sub, sid + ".json")
        with open(path, "w") as f:
            json.dump(data, f)
        if mtime:
            os.utime(path, (mtime, mtime))


def report_at(folder, mtime):
    path = os.path.join(folder, "report.html")
    open(path, "w").close()
    os.utime(path, (mtime, mtime))


class Notice(unittest.TestCase):
    def setUp(self):
        self.dir, self.state, self.now = tempfile.mkdtemp(), tempfile.mkdtemp(), time.time()

    def test_silent_when_fresh(self):
        report_at(self.dir, self.now - 5 * DAY)
        self.assertIsNone(tune_notice.notice(self.dir, self.now, self.state))

    def test_old_report_warns_once_a_day(self):
        report_at(self.dir, self.now - 40 * DAY)
        self.assertIn("40 days", tune_notice.notice(self.dir, self.now, self.state))
        self.assertIsNone(tune_notice.notice(self.dir, self.now, self.state))
        self.assertIsNotNone(tune_notice.notice(self.dir, self.now + 2 * DAY, self.state))

    def test_many_new_sessions_warn(self):
        report_at(self.dir, self.now - 5 * DAY)
        for i in range(21):
            make(self.dir, f"s{i}", mtime=self.now - DAY)
        self.assertIn("21 sessions", tune_notice.notice(self.dir, self.now, self.state))

    def test_no_report_and_few_sessions_is_silent(self):
        make(self.dir, "a")
        self.assertIsNone(tune_notice.notice(self.dir, self.now, self.state))

    def test_missing_folder_never_raises(self):
        self.assertIsNone(tune_notice.notice(os.path.join(self.dir, "nope"), self.now, self.state))


class Stats(unittest.TestCase):
    def test_small_groups_say_few_data(self):
        d = tempfile.mkdtemp()
        make(d, "a", frict=3, agent=1)
        self.assertIn("few data", tune_stats.report(tune_stats.load(d)))

    def test_groups_with_enough_sessions_show_average(self):
        d = tempfile.mkdtemp()
        for i in range(10):
            make(d, f"a{i}", frict=2, agent=1)
        for i in range(10):
            make(d, f"b{i}", frict=0)
        out = tune_stats.report(tune_stats.load(d))
        self.assertIn("with Agent", out)
        self.assertIn("friction avg 2.0", out)
        self.assertIn("friction avg 0.0", out)

    def test_empty_folder_asks_for_insights(self):
        self.assertIn("/insights", tune_stats.report(tune_stats.load(tempfile.mkdtemp())))


if __name__ == "__main__":
    unittest.main()
