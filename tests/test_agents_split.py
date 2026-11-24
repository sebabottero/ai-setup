"""One owner per rule: CONTRIBUTING.md owns the process, the root AGENTS.md owns what an agent runs and must not do
here, core/AGENTS.md owns the generic rules. The duplicate check catches exact sentence matches only (code blocks are
ignored); a reworded rule needs a human reviewer."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_LEN = 25  # shorter fragments ("Run the tests") are headings, not rules


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def sentences(text):
    """Rule sentences: markdown stripped, split on line ends and sentence ends, lowercased, whitespace collapsed."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*`_]", "", text)
    out = set()
    for line in text.splitlines():
        line = re.sub(r"^\s*(#+|[-|]|\d+\.)\s*", "", line)
        for part in re.split(r"(?<=[.!?:])\s+", line):
            part = re.sub(r"\s+", " ", part).strip(" .|").lower()
            if len(part) >= MIN_LEN:
                out.add(part)
    return out


def duplicates(a, b):
    return sorted(sentences(a) & sentences(b))


class AgentsSplit(unittest.TestCase):
    def test_root_agents_is_short_and_has_the_essentials(self):
        text = read("AGENTS.md")
        self.assertLess(len(text.splitlines()), 60)
        self.assertIn("python3 -I -m unittest discover -s tests", text)
        for folder in ("core/", "adapters/", "docs/", "tests/"):
            self.assertIn(f"`{folder}`", text)
        self.assertIn("(CONTRIBUTING.md)", text)

    def test_cheatsheet_note_lives_in_root_agents_not_in_core(self):
        self.assertIn("docs/cheatsheet.html", read("AGENTS.md"))
        self.assertNotIn("cheatsheet", read("core/AGENTS.md").lower())

    def test_contributing_alone_states_weakening_tests_and_updating_docs(self):
        self.assertRegex(read("CONTRIBUTING.md"), r"(?i)do not weaken a test")
        self.assertRegex(read("CONTRIBUTING.md"), r"(?i)update the docs")
        root = read("AGENTS.md")
        self.assertNotRegex(root, r"(?i)weaken")
        self.assertNotRegex(root, r"(?i)update the (docs|cheatsheet)")

    def test_no_rule_sentence_is_in_both_root_agents_and_contributing(self):
        dup = duplicates(read("AGENTS.md"), read("CONTRIBUTING.md"))
        self.assertEqual(dup, [], "state each rule once; link to the owner instead")

    def test_the_duplicate_check_catches_a_repeated_line(self):
        root = read("AGENTS.md") + "\n- Do not weaken a test to make it pass.\n"
        self.assertEqual(duplicates(root, read("CONTRIBUTING.md")), ["do not weaken a test to make it pass"])


if __name__ == "__main__":
    unittest.main()
