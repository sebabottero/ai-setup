"""Repo-declared HTML docs. Criterion 7: given a repo whose AGENTS.md or CONTRIBUTING.md declares HTML for human docs,
when the ticket-flow docs stage runs, then the writer produces them with the repo-doc template in English; with no such
declaration, the docs stage behaves as today."""
import os, re, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
VG = os.path.join(ROOT, "core", "skills", "visual-guides", "SKILL.md")
TICKET_FLOW = os.path.join(ROOT, "core", "skills", "ticket-flow", "SKILL.md")
BUILDER = os.path.join(ROOT, "core", "agents", "sub-builder.md")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def declared_command():
    """The one detection command written in the visual-guides skill, inside a ```sh block."""
    blocks = re.findall(r"```sh\n(.*?)```", read(VG), re.S)
    lines = [l.strip() for b in blocks for l in b.splitlines() if "human docs" in l.lower()]
    assert len(lines) == 1, f"expected one detection line in a sh block, found {lines}"
    assert re.fullmatch(r"cat AGENTS\.md CONTRIBUTING\.md 2>/dev/null \| grep -iE '[^']+'", lines[0]), lines[0]
    return lines[0]


def declares(files):
    """Run the skill's command in a temp repo; exit 0 means declared, 1 means not."""
    with tempfile.TemporaryDirectory() as d:
        for name, text in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write(text)
        r = subprocess.run(["sh", "-c", declared_command()], cwd=d, capture_output=True, text=True)
        assert r.returncode in (0, 1), f"exit {r.returncode}: {r.stderr}"
        assert (r.returncode == 0) == bool(r.stdout.strip())
        return r.returncode == 0


class Criterion7DeclarationDetection(unittest.TestCase):
    def test_agents_md_declaring_html_matches(self):
        self.assertTrue(declares({"AGENTS.md": "# Rules\nHuman docs: html\n"}))

    def test_contributing_md_list_item_any_case_matches(self):
        self.assertTrue(declares({"CONTRIBUTING.md": "# Rules\n- human docs: HTML\n"}))

    def test_a_repo_with_only_one_of_the_two_files_is_detected(self):
        self.assertTrue(declares({"AGENTS.md": "Human docs: html\n"}))
        self.assertTrue(declares({"CONTRIBUTING.md": "Human docs: html\n"}))
        self.assertFalse(declares({"AGENTS.md": "Human docs: md\n"}))
        self.assertFalse(declares({"CONTRIBUTING.md": "Be nice.\n"}))

    def test_declaration_followed_by_punctuation_matches(self):
        self.assertTrue(declares({"AGENTS.md": "* Human docs: html.\n"}))

    def test_repo_without_a_declaration_does_not_match(self):
        self.assertFalse(declares({"AGENTS.md": "# Rules\nBe nice.\n"}))
        self.assertFalse(declares({}))

    def test_other_formats_do_not_match(self):
        for line in ("Human docs: md", "Human docs: htmlx", "Human docs: html-free", "Human docs: html_x"):
            with self.subTest(line=line):
                self.assertFalse(declares({"AGENTS.md": line + "\n"}))


class Criterion7DocsStageWording(unittest.TestCase):
    BULLETS = (
        "- **Docs, at the end, by the same writer:**",
        "  - read the repo's docs rules first (CONTRIBUTING, a `/document` command, CLAUDE.md); they win over this;",
        "  - **the code is the authority**: check every endpoint, field or class in the code before writing it down;",
        "  - document what the code does today; what is pending goes where the project notes say (if they say nothing, in the receipt);",
        "  - match the depth and tone of the neighbouring docs and run the docs checks if they exist.",
    )

    def docs_block(self):
        text = read(TICKET_FLOW)
        start = text.index("- **Docs, at the end, by the same writer:**")
        return text[start:text.index("\n## 3", start)]

    def test_existing_docs_stage_bullets_are_kept_verbatim(self):
        text = read(TICKET_FLOW)
        for bullet in self.BULLETS:
            with self.subTest(bullet=bullet):
                self.assertIn(bullet, text)

    def test_docs_stage_uses_repo_doc_in_english_only_when_declared(self):
        block = self.docs_block()
        extra = [l for l in block.splitlines() if l not in self.BULLETS and l.strip()]
        self.assertEqual(len(extra), 1, extra)
        line = extra[0].lower()
        for word in ("repo-doc", "english", "human docs: html", "visual-guides", "as today"):
            self.assertIn(word, line)
        self.assertRegex(line, r"\bif\b.*(match|declar)")

    def test_ticket_flow_keeps_banned_words_out(self):
        text = read(TICKET_FLOW).lower()
        self.assertNotIn("critical", text)
        self.assertNotIn("warning", text)

    def test_sub_builder_keeps_its_docs_sentence_and_adds_the_clause(self):
        text = read(BUILDER)
        self.assertIn("- Docs, at the end: read the repo's docs rules first; the code is the authority, "
                      "so check every name in the code before writing it down.", text)
        line = next(l for l in text.splitlines() if l.startswith("- Docs, at the end"))
        for word in ("`AGENTS.md`", "`CONTRIBUTING.md`", "`Human docs: html`", "`repo-doc`", "English", "visual-guides"):
            self.assertIn(word, line)
        self.assertNotIn("{{", line)
        self.assertNotIn("grep", line)

    def test_visual_guides_documents_the_declaration_and_precedence(self):
        text = read(VG)
        section = text[text.index("## Human docs in a repo"):text.index("## Gate pages")]
        for word in ("Human docs: html", "English", "repo-doc", "every other", "plain line", "printed line"):
            self.assertIn(word, section)


if __name__ == "__main__":
    unittest.main()
