"""Phase 3, criteria first: grillme writes criteria.md, ticket-flow needs it at Gate 1 (short route for low risk),
sub-tester maps one test per criterion, sub-review lists criteria without a test. Wording checks only:
prompt text cannot be behaviour-tested."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GRILLME = os.path.join(ROOT, "core", "skills", "grillme", "SKILL.md")
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
SUB_TESTER = os.path.join(ROOT, "core", "agents", "sub-tester.md")
SUB_REVIEW = os.path.join(ROOT, "core", "agents", "sub-review.md")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def flat(path):
    """File text lowercased with whitespace collapsed, so line wrapping does not matter."""
    return re.sub(r"\s+", " ", read(path)).lower()


class CriteriaFirst(unittest.TestCase):
    def assert_all(self, path, *needles):
        text = flat(path)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} lacks: {needle}")

    def test_1_no_criteria_file_ticket_flow_stops_at_gate_1_and_offers_grillme(self):
        self.assert_all(TICKET_FLOW, "handoffs/<ticket>/criteria.md", "no criteria.md", "stop", "offer", "`grillme`")
        gate = flat(TICKET_FLOW).split("gate 1: plan approval")[1].split("## 2 · build")[0]
        self.assertIn("criteria.md", gate, "Gate 1 must require criteria.md")

    def test_2_criteria_file_with_4_items_sub_tester_writes_4_tests_quoting_each_and_maps_item_to_test(self):
        self.assert_all(SUB_TESTER, "criteria.md", "one test per criterion", "name quotes", "item → test")

    def test_3_criterion_without_a_test_sub_review_lists_it_as_not_covered(self):
        self.assert_all(SUB_REVIEW, "criteria.md", "without a test", '"not covered"')

    def test_4_low_risk_change_ticket_flow_uses_short_route_and_still_writes_review_report(self):
        self.assert_all(
            TICKET_FLOW, "short route", "risk tiers", "tier low", "one line",
            "skip exploration and planning", "sub-review", "review_report.py",
            "<dev root>/reviews/<repo>/<branch>.md",
        )

    def test_5_grillme_closing_writes_criteria_md_in_goal_out_of_scope_criteria_done_shape(self):
        self.assert_all(
            GRILLME, "<dev root>/handoffs/<ticket>/criteria.md", "## goal", "## out of scope",
            "## criteria", "given/when/then", "3-7", "## done",
        )

    def test_6_short_route_keeps_scope_contract_and_criteria_md_wins_over_plan(self):
        self.assert_all(
            TICKET_FLOW, "0a scope contract still applies in short form", "`criteria.md` wins",
            "no \"risk tiers\" section", "short form: goal + 1-3 criteria",
        )


if __name__ == "__main__":
    unittest.main()
