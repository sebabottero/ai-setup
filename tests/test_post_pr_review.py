"""Post-PR re-review: after commit + push + PR, ticket-flow runs sub-review on the committed change against criteria.md.
Wording checks only: prompt text cannot be behaviour-tested."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")


def flat(path):
    """File text lowercased with whitespace collapsed, so line wrapping does not matter."""
    with open(path, encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).lower()


class PostPrReview(unittest.TestCase):
    def assert_all(self, *needles):
        text = flat(TICKET_FLOW)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"ticket-flow/SKILL.md lacks: {needle}")

    def test_1_sub_review_on_committed_change_against_criteria_with_report(self):
        self.assert_all(
            "4 · post-pr re-review", "`sub-review` on the committed change against `criteria.md`",
            "only slice k's criteria", "python3 -i {{ai_setup}}/core/guard/review_report.py", "tree hash matches the commit",
        )

    def test_2_blocker_or_warning_stops_and_user_decides(self):
        self.assert_all(
            "blocker or warning", "stop and show it", "same pr", "nothing is fixed or pushed on its own",
        )

    def test_3_ok_at_gate_2_to_post_comment_nits_do_not_block(self):
        self.assert_all(
            "ok at gate 2 to post it as a comment on the pr", "`gh pr comment`", "only after my ok",
            "nits go in that comment and do not block",
        )

    def test_4_short_route_applies_it(self):
        self.assert_all("short route", "the same re-review applies against the 1-3 line `criteria.md`")

    def test_5_stage_3_stays_against_plan_and_angles_differ(self):
        self.assert_all(
            "still compares against `plan.md`", "different angles", "plan (stage 3) vs criteria (stage 4)",
        )

    def test_6_brief_carries_only_commit_criteria_path_and_report_path(self):
        self.assert_all(
            "the brief carries only the commit, the path to `criteria.md` and the report path",
            "no summary of what was built or what passed",
        )

    def test_7_worktree_deleted_only_after_stage_4(self):
        self.assert_all(
            "the worktree stays until it is done",
            "only after stage 4 is done (and any fix-commit decision), if you created the worktree, delete it",
        )

    def test_8_follow_up_message_is_part_of_gate_2(self):
        self.assert_all(
            "arrive in a follow-up gate 2 message after the pr; that ask is part of gate 2",
        )


if __name__ == "__main__":
    unittest.main()
