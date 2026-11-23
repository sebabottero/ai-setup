"""Review quality: sub-review findings are a fixed table (severity, triage, reason) and ticket-flow stops after 2 rounds
with blocking or major findings. Wording checks only: prompt text cannot be behaviour-tested; the script is tested in test_guard."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
SUB_REVIEW = os.path.join(ROOT, "core", "agents", "sub-review.md")


def flat(path):
    """File text lowercased with whitespace collapsed, so line wrapping does not matter."""
    with open(path, encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).lower()


class ReviewQuality(unittest.TestCase):
    def assert_in(self, path, *needles):
        text = flat(path)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{os.path.basename(path)} lacks: {needle}")

    def test_7_issues_are_a_fixed_table_with_severity_triage_and_reason(self):
        self.assert_in(
            SUB_REVIEW, "severity (`blocking` / `major` / `minor` / `nit`)", "triage (`fix_now` / `defer` / `reject`)",
            "one-line reason", "file:line",
        )

    def test_7_old_severity_words_are_gone_from_the_prompts(self):
        for path in (SUB_REVIEW, TICKET_FLOW):
            text = flat(path)
            for old in ("critical", "warning"):
                self.assertNotRegex(text, rf"\b{old}\b", f"{os.path.basename(path)} still says {old}")

    def test_7_slice_finding_uses_the_new_severity(self):
        self.assert_in(SUB_REVIEW, "is a finding (major)")

    def test_8_two_rounds_with_blocking_or_major_stop_at_the_next_gate(self):
        self.assert_in(
            TICKET_FLOW, "blocking or major: stop and show it", "stages 3 and 4",
            "still has `blocking` or `major` findings after 2 review rounds", "do not start round 3",
            "ask me at the next gate", "review_report.py rounds --dir <worktree> --stage <3|4>", "stop=yes",
        )


if __name__ == "__main__":
    unittest.main()
