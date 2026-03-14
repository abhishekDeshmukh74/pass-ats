# Rewriter Service — `rewriter.py`

## Purpose

Rewrites the original PDF resume **in-place** using AI-generated `{old, new}` replacement pairs.
The output PDF preserves the original layout, fonts, colours, and formatting — only the text content changes.

## How It Works

### Pipeline

1. **Receive** `file_bytes` (original PDF) + `ResumeData` (AI output with `.replacements` list).
2. **Extract embedded fonts** from the document into a cache (`_build_font_cache`) so we can re-insert text using the *exact same* typeface (e.g., `LMRoman10-Regular` from LaTeX PDFs).
3. **For each page**, collect spans grouped by **block → line** (not a flat list — prevents cross-block matching).
4. **For each replacement**:
   - Search each block's *lines* for a normalised match of the `old` text (sliding-window over contiguous lines).
   - Only match within a single block — never across blocks/sections.
5. **Redact** matched areas with **one redact rect per group** (union of all matched line bboxes), using `graphics=0` to preserve line-art (horizontal separator lines).
6. **Word-wrap** the `new` text to fit the same line widths as the original lines (`_wrap_text_to_lines`).
7. **Insert** each wrapped line via `TextWriter` at the original line's `(x0, baseline)` position, using the embedded font and per-line auto-shrink.
8. If zero replacements matched, return the original PDF unchanged (no corruption risk).

### Font Reuse (Embedded Fonts)

**Critical for format preservation**: Instead of falling back to Base-14 fonts (Times-Roman, Helvetica), the rewriter extracts the actual fonts embedded in the PDF using `doc.extract_font(xref)` and creates `fitz.Font` objects from the font buffers. This means:

- A LaTeX PDF with `LMRoman10-Regular` will have replacement text in `LMRoman10-Regular`
- A Word PDF with `Calibri` will have replacement text in `Calibri`
- Only when extraction fails **or the font is a subset missing glyphs for the replacement text** does it fall back to Base-14 (`tiro`, `helv`, etc.)

The font cache is keyed by: full basefont name (e.g., `WRAHST+LMRoman10-Regular`), clean name without subset prefix (`LMRoman10-Regular`), and short PDF name (`F43`).

**Glyph validation** (`_font_can_render`): Before using an extracted font, every non-space character in the replacement text is checked via `font.has_glyph(ord(ch))`. If any glyph is missing (common with subset fonts), the font is rejected and the style-matched Base-14 fallback is used instead — preventing garbled characters.

### Block-Scoped, Line-Aware Matching

Spans are grouped by PDF block, then by line within the block. Matching uses a sliding window over *lines* (not flat spans), which handles multi-line text blocks (like bullet points that wrap across 2-3 lines) correctly.

```
Block 0 (summary): [Line0[spans], Line1[spans], ...]  ← match within lines of this block
Block 1 (bullet):  [Line0[spans], Line1[spans], ...]  ← match within lines of this block
```

### Text Normalisation (`_norm`) and Sanitisation (`_sanitize_text`)

Both the `old` text from AI and the span text from the PDF are normalised before comparison:

- Unicode NFKC normalisation (collapses ligatures like fi → fi)
- Common PDF character replacements (smart quotes → straight, em/en dash → hyphen, bullet chars → `*`, non-breaking space → space)
- Whitespace collapse (`\s+` → single space)
- **Spaces before punctuation** are removed (`typescript) ,` → `typescript),`) — crucial for LaTeX PDFs with inter-character spacing
- Case-insensitive comparison

**Output sanitisation** (`_sanitize_text`): Before insertion, the AI's replacement text is normalised to plain ASCII equivalents (smart quotes → straight, em/en dashes → hyphens, zero-width chars removed). This prevents rendering failures when the target font lacks glyphs for fancy Unicode characters.

### Line Info & Font Selection (`_line_info`)

For each matched line, `_line_info` returns `(x0, baseline, width, height, font_name, font_size)`:

- **Baseline** uses the span `origin` field (true text baseline), not `bbox.y1` (descender bottom)
- **Font selection**: when a line has **mixed Bold and non-Bold** spans (common in LaTeX PDFs where keywords are bolded), the Regular variant is preferred. This is because:
  - We can't know which words in the *new* text should be bold
  - Bold glyphs are wider, causing unnecessary auto-shrink
  - Purely-bold lines (headings) keep their bold font
- **Font size** is the dominant size by character count

### Line-by-Line Insertion

Instead of `insert_textbox` (which wraps text independently and produces different line breaks), the rewriter:

1. Preserves the exact y-position of each original line
2. Word-wraps the new text using the **maximum line width** across matched lines (prevents short trailing lines from forcing awkward breaks)
3. Inserts each line individually at `(x0, baseline)` via `TextWriter.append()`
4. Per-line auto-shrink (up to ~34%) if a line still overflows

### Redaction Strategy

- **One rect per matched line** (tight bbox around content spans)
- White fill `(1, 1, 1)` ensures clean removal of old glyphs with no remnants
- `graphics=fitz.PDF_REDACT_IMAGE_NONE` → preserves decorative elements (horizontal lines, borders)
- Operations grouped by text colour, one `TextWriter` per colour

## Key Invariants

- **Never return a corrupt PDF** — if zero replacements match, return original bytes unchanged.
- **Block-scoped matching** — never match spans across different PDF blocks.
- **Claimed spans** — once a span is matched by one replacement, it's excluded from subsequent matches.
- **Redactions are batched** — all per-page redactions are queued, then applied in one `apply_redactions()` call.
- **Embedded fonts preferred** — Base-14 fallback only when font extraction fails.

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| PDF unchanged | AI `old` text doesn't match any spans | Check AI prompt; verify `_norm` handles the characters; check logs |
| Text overlaps | Replacement text longer than original | Auto-fit scales down; prompt tells AI to keep ±20% length |
| Wrong font | Embedded font is a subset missing glyphs for new text | `_font_can_render` detects this and falls back to Base-14 |
| Garbled chars | AI produced smart quotes / em-dashes the font can't render | `_sanitize_text` maps to ASCII equivalents before insertion |
| Huge combined bbox | Matching crossed blocks | Fixed by block-scoped matching |
| Line-art removed | `apply_redactions` destroyed graphics | White-fill rects are per-line and tight; `graphics=IMAGE_NONE` preserves paths |
| Spaces before punctuation break matching | LaTeX inter-char spacing | Fixed by `_norm` removing pre-punctuation spaces |

## Dependencies

- **PyMuPDF (`fitz`)** — PDF manipulation (spans, redactions, TextWriter, Font extraction)
- **`backend.models.ResumeData`** — Pydantic model with `.replacements: list[TextReplacement]`
