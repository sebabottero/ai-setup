"""Plan stage: criteria map in plan.md and a plan critic before Gate 1.
Wording checks only: prompt text cannot be behaviour-tested."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
SUB_REVIEW = os.path.join(ROOT, "core", "agents", "sub-review.md")


def flat(path):
    """File text lowercased with whitespace collapsed, so line wrapping does not matter."""
    with open(path, encoding="utf-8") as f:
        return re.sub(r"\s+", " ", f.read()).lower()


class PlanCritic(unittest.TestCase):
    def assert_in(self, path, *needles):
        text = flat(path)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{os.path.basename(path)} lacks: {needle}")

    def test_1_plan_carries_a_criteria_map_and_flags_extra_scope(self):
        self.assert_in(
            TICKET_FLOW,
            "a **criteria map**: each criterion → the step(s) and test that cover it",
            "a step with no criterion is extra scope", "list it under \"extras\" in the gate 1 summary",
        )

    def test_2_critic_runs_on_full_route_one_round_before_gate_1(self):
        self.assert_in(
            TICKET_FLOW,
            "**plan critic.** full route only. before gate 1, one `sub-review` (read-only, one round) attacks `plan.md`",
        )

    def test_3_critic_returns_findings_and_writes_no_report(self):
        self.assert_in(
            TICKET_FLOW,
            "it returns its findings as its message and skips the report step (step 5)",
            "nothing is written at the review report path the merge gate reads",
        )

    def test_4_fixes_stay_inside_contract_and_criteria(self):
        self.assert_in(
            TICKET_FLOW,
            "only inside the 0a contract and `criteria.md`; a fix that would change either is unresolved",
            "gate 1 mentions the critic only for unresolved findings",
        )

    def test_5_sub_review_step_5_is_conditional_on_the_brief(self):
        self.assert_in(
            SUB_REVIEW,
            "unless the brief says to return findings only", "write no file",
        )

    def test_6_sub_review_step_5_keeps_the_report_instructions(self):
        self.assert_in(
            SUB_REVIEW,
            "review_report.py header", "write the file there with the write tool",
            "never edit those lines", "findings only, in the output shape above, when the brief asks for that",
        )


if __name__ == "__main__":
    unittest.main()
