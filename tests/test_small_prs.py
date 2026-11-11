"""Small PRs: grillme proposes `## Slices`, ticket-flow shows a verdict line at Gate 1 and scopes a build to one slice,
core/AGENTS.md has the rule for sessions without ticket-flow, sub-review flags diffs outside their slice. Wording checks
only: prompt text cannot be behaviour-tested."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
GRILLME = os.path.join(ROOT, "core", "skills", "grillme", "SKILL.md")
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
AGENTS = os.path.join(ROOT, "core", "AGENTS.md")
SUB_REVIEW = os.path.join(ROOT, "core", "agents", "sub-review.md")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def flat(path):
    """File text lowercased with whitespace collapsed, so line wrapping does not matter."""
    return re.sub(r"\s+", " ", read(path)).lower()


class SmallPrs(unittest.TestCase):
    def assert_all(self, path, *needles):
        text = flat(path)
        for needle in needles:
            self.assertIn(needle.lower(), text, f"{os.path.basename(os.path.dirname(path))}/{os.path.basename(path)} lacks: {needle}")

    def test_1_grillme_closing_adds_slices_section_only_when_split(self):
        self.assert_all(
            GRILLME, "## slices", "criteria numbers per pr", "dependencies",
            "separately", "mixes topics", "single pr: no `## slices` section",
        )

    def test_2_gate_1_carries_one_verdict_line_and_ok_accepts_it(self):
        self.assert_all(
            TICKET_FLOW, "single pr (~n lines, 1 topic)", "split into n: signals x, y", "verdict line",
            "my ok at gate 1 accepts it", "one slice per run", "only when you recommend it",
            "only if it depends on its code",
        )

    def test_3_signal_rule_and_150_line_floor(self):
        self.assert_all(
            TICKET_FLOW, "one strong signal", "mixed topics", ">400 lines", "two weak",
            "several modules or layers", "independently testable criteria", "below ~150 estimated lines",
            "always a single pr",
        )

    def test_4_slice_k_scopes_plan_allowlist_and_review(self):
        self.assert_all(
            TICKET_FLOW, "has `## slices`", "slice k", "plan, the writer's allowlist and the review", "names slice k in the run's args", "first slice not yet merged",
        )

    def test_5_agents_rule_for_sessions_without_ticket_flow_expires(self):
        self.assert_all(
            AGENTS, "(until 2027-01-31)", "propose the split before writing",
            "fewer than half of the splits", "size per pr did not drop", "adjust the threshold or remove",
        )

    def test_6_sub_review_flags_diff_outside_slice_or_mixing_topics(self):
        self.assert_all(SUB_REVIEW, "outside its slice", "mixes topics", "is a finding (warning)")


if __name__ == "__main__":
    unittest.main()
