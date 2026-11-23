"""The README rules in CONTRIBUTING.md ("README and GitHub About") that a machine can check."""
import os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = ["Why use it", "Quick start", "What you get", "Is it for you?", "Limits", "Documentation", "License"]


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def slug(heading):
    """GitHub anchor of a heading: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^a-z0-9 \-]", "", heading.lower()).replace(" ", "-")


class ReadmeRules(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_stays_short(self):
        self.assertLessEqual(len(self.text.splitlines()), 90, "move detail to docs/REFERENCE.md")

    def test_sections_in_order(self):
        heads = re.findall(r"^## (.+)$", self.text, re.M)
        self.assertEqual(heads, SECTIONS)

    def test_demo_gif_comes_before_why_and_exists(self):
        m = re.search(r"!\[[^\]]*\]\((docs/assets/[^)]+\.gif)\)", self.text)
        self.assertTrue(m, "no demo GIF")
        self.assertLess(m.start(), self.text.index("## Why use it"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, m.group(1))))

    def test_benefit_lead(self):
        lead = [l for l in self.text.splitlines() if l.startswith("**")][0]
        self.assertIn("without handing it the keys", lead)

    def test_layer_table_has_eight_layers_with_existing_evidence(self):
        block = self.text.split("## What you get")[1].split("\n## ")[0]
        rows = [l for l in block.splitlines() if l.startswith("| ") and "---" not in l][1:]
        self.assertEqual(len(rows), 8)
        for row in rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            self.assertIn(cells[2], ("done", "partial"), row)
            path = re.search(r"\]\(([^)]+)\)", cells[3])
            self.assertTrue(path and os.path.exists(os.path.join(ROOT, path.group(1))), f"evidence missing: {row}")

    def test_local_links_and_reference_anchors_resolve(self):
        ref_heads = {slug(h) for h in re.findall(r"^#{2,3} (.+)$", read("docs/REFERENCE.md"), re.M)}
        for target in re.findall(r"\]\(([^)]+)\)", self.text):
            if target.startswith(("http", "mailto")):
                continue
            path, _, anchor = target.partition("#")
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), f"broken link: {target}")
            if path == "docs/REFERENCE.md" and anchor:
                self.assertIn(anchor, ref_heads, f"missing anchor: {target}")

    def test_about_text_is_recorded_and_short(self):
        m = re.search(r"Current text:\n\s+`([^`]+)`", read("CONTRIBUTING.md"))
        self.assertTrue(m, "CONTRIBUTING.md must record the About text")
        self.assertLessEqual(len(m.group(1)), 350)
        self.assertTrue(m.group(1).startswith("Let your AI coding agent work fast"))


if __name__ == "__main__":
    unittest.main()
