---
name: convert-to-markdown
description: Convert a PDF, Word, PowerPoint, Excel, HTML, image or audio file to Markdown with the `markitdown` CLI before reading it, so it costs far fewer tokens than the original. Use for "convertí esto a markdown", "pasalo a markdown", "ahorrá tokens con este PDF/doc", "resumime este documento", or whenever about to read a .pdf/.docx/.pptx/.xlsx/.html file that is not already small and text-based.
---

# Convert to Markdown before reading

Goal: read the content, not the container. A PDF/docx/pptx can cost far more tokens than its text would in Markdown.

1. Skip this for files already small and plain text (`.md`, `.txt`, `.csv`, short `.html`) — converting them wastes a step for no savings.
2. Check the tool exists: `which markitdown`. If missing, tell the user to install it once (`uv tool install 'markitdown[all]'` or `pipx install 'markitdown[all]'`) — do not install it yourself without asking, it pulls ~50 packages.
3. Convert into the scratchpad directory, never next to the original: `markitdown <file> > <scratchpad>/<basename>.md`.
4. Read the generated `.md` instead of the original file.
5. If the conversion looks broken (empty, garbled table, missing content), fall back to reading the original directly and say so — don't build an answer on a bad conversion.
