# Parser Service — `parser.py`

## Purpose

Extracts plain text and styled HTML from an uploaded PDF resume using PyMuPDF.

## How It Works

1. Opens PDF from raw bytes using `fitz.open(stream=..., filetype="pdf")`.
2. For each page:
   - `page.get_text("text")` → plain text (used as AI input in the LangGraph agent pipeline).
   - `page.get_text("html")` → styled HTML preserving fonts, colours, layout (used for frontend preview of the original).
3. Returns `(text, html, file_b64, file_type)`.

## Critical: Text Representation Consistency

The plain text returned here is sent to the multi-agent pipeline, where Agent 4 (Rewriter) must return **verbatim substrings** of it as `old` values in the replacements array. Agent 5 (QA) validates these substrings exist. The rewriter service (`rewriter.py`) then matches these `old` values against span-level text from `page.get_text("dict")`.

**`get_text("text")` specifics:**
- Inserts `\n` between lines within a block
- Inserts `\n\n` between blocks
- Handles ligatures differently from dict-level spans
- May normalise some Unicode characters

The rewriter accounts for these differences via Unicode NFKC normalisation, character mapping, and space injection between consecutive spans.

## Returns

| Field | Type | Usage |
|-------|------|-------|
| `text` | `str` | Plain text → sent to AI for analysis |
| `html` | `str` | Styled HTML → frontend original preview |
| `file_b64` | `str` | Base64 original PDF → sent back to generate endpoint |
| `file_type` | `str` | Always `"pdf"` |
