"""
rewriter.py — Replace text content in an original PDF resume while keeping
all formatting (fonts, colours, layout) intact.

Strategy:
  1. Extract embedded fonts so we can re-insert with the *exact* typeface.
  2. Collect spans grouped by block (prevents cross-section matching).
  3. Match each AI "old" text within a single block's lines.
  4. Redact the matched area with a single rect per group (minimal drawings).
  5. Word-wrap the "new" text into the SAME line positions/widths as the
     original, then insert each line via TextWriter at the original baseline.

This preserves: y-positions, line count, left margin, original font & size.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections import Counter

import fitz  # PyMuPDF

from backend.models import ResumeData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Font cache — extract embedded fonts from the document for reuse
# ---------------------------------------------------------------------------

def _build_font_cache(doc) -> dict[str, fitz.Font]:
    """Return {pdf_font_name: fitz.Font} for every usable embedded font."""
    cache: dict[str, fitz.Font] = {}
    seen_xrefs: set[int] = set()
    for page_idx in range(len(doc)):
        for entry in doc.get_page_fonts(page_idx, full=True):
            xref = entry[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            _, _, _, basefont, name, *_ = entry
            fontdata = doc.extract_font(xref)
            fbuffer = fontdata[3]
            if not fbuffer:
                continue
            try:
                font = fitz.Font(fontbuffer=fbuffer)
                # Index by both the base font name and the short name
                cache[basefont] = font
                # Strip subset prefix (e.g. "WRAHST+LMRoman10-Regular" → "LMRoman10-Regular")
                clean = basefont.split("+", 1)[-1] if "+" in basefont else basefont
                cache[clean] = font
                if name:
                    cache[name] = font
            except Exception:
                logger.debug("Could not load font xref=%d (%s)", xref, basefont)
    return cache


# Base-14 fallback (used only when embedded font unavailable)
_BASE14_FALLBACK = {
    "bold_italic_serif": "tibi", "bold_serif": "tibo",
    "italic_serif": "tiit", "regular_serif": "tiro",
    "bold_italic_sans": "hebi", "bold_sans": "hebo",
    "italic_sans": "heit", "regular_sans": "helv",
    "bold_italic_mono": "cobi", "bold_mono": "cobo",
    "italic_mono": "coit", "regular_mono": "cour",
}


def _base14_name(span: dict) -> str:
    flags = span.get("flags", 0)
    is_bold = bool(flags & (1 << 4))
    is_italic = bool(flags & (1 << 1))
    font = span.get("font", "").lower()
    if any(s in font for s in ("courier", "mono", "consolas", "menlo", "code")):
        family = "mono"
    elif any(s in font for s in ("arial", "helvetica", "sans", "calibri", "verdana")):
        family = "sans"
    else:
        family = "serif"
    style = ("bold_" if is_bold else "") + ("italic_" if is_italic else "") or "regular_"
    return _BASE14_FALLBACK[f"{style}{family}"]


def _font_can_render(font: fitz.Font, text: str) -> bool:
    """Return True if *font* has glyphs for every non-space char in *text*."""
    for ch in text:
        if ch.isspace():
            continue
        if not font.has_glyph(ord(ch)):
            return False
    return True


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_WS = re.compile(r"\s+")

_CHAR_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
    "\u2026": "...",
    "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl",
    "\u00a0": " ",
    "\u2022": "*", "\u25cf": "*",
    "\u25cb": "*", "\u00b7": "*",
})


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKC", t)
    t = t.translate(_CHAR_MAP)
    t = _WS.sub(" ", t).strip().lower()
    # Collapse spaces before punctuation (LaTeX PDFs add inter-char spacing)
    t = re.sub(r" ([,.\);:?!])", r"\1", t)
    return t


# Characters the AI may produce that many subset fonts cannot render.
# Map them to plain ASCII equivalents before insertion.
_OUTPUT_CHAR_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",       # smart single quotes
    "\u201c": '"', "\u201d": '"',       # smart double quotes
    "\u2013": "-", "\u2014": "-",       # en/em dash
    "\u2026": "...",                     # ellipsis
    "\u00a0": " ",                       # non-breaking space
    "\u200b": "",                        # zero-width space
    "\u200c": "", "\u200d": "",         # zero-width non/joiner
    "\ufeff": "",                        # BOM
})


def _sanitize_text(text: str) -> str:
    """Normalise replacement text to commonly renderable characters."""
    return unicodedata.normalize("NFKC", text).translate(_OUTPUT_CHAR_MAP)


# ---------------------------------------------------------------------------
# Span collection — grouped by block, retaining line structure
# ---------------------------------------------------------------------------

_Line = list[dict]         # spans in one visual line
_Block = list[_Line]       # lines in one text block


def _collect_blocks(page) -> list[_Block]:
    """Spans grouped by block → line.  Each line is a list of spans."""
    page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    blocks: list[_Block] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines: _Block = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if spans:
                lines.append(spans)
        if lines:
            blocks.append(lines)
    return blocks


def _flat(block: _Block) -> list[dict]:
    """Flatten a block's lines into a single span list."""
    return [s for line in block for s in line]


# Characters used as bullet markers in itemize / unordered lists
_BULLET_CHARS = frozenset("\u2022\u25cb\u25cf\u25aa\u25b8\u25b9\u2013\u2014\u00b7\u2043\u2023\u25b6\u25ba")


def _content_spans(line: _Line) -> _Line:
    """Return spans after skipping leading bullet-marker glyphs and whitespace.

    Preserves bullet markers during redaction so they are not erased.
    """
    for i, span in enumerate(line):
        text = span.get("text", "").strip()
        if text and not all(c in _BULLET_CHARS for c in text):
            return line[i:]
    return line


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _find_matching_lines(block: _Block, target: str, claimed: set[int],
                         ) -> list[_Line] | None:
    """Find contiguous *lines* whose combined text contains *target*.

    Only considers unclaimed spans. Returns the matching lines or None.
    """
    norm_target = _norm(target)
    if not norm_target:
        return None

    # Build per-line texts, skipping entirely-claimed lines
    line_texts: list[str] = []
    usable: list[int] = []          # indices into block
    for li, line in enumerate(block):
        avail = [s for s in line if id(s) not in claimed]
        if not avail:
            continue
        txt = " ".join(s.get("text", "") for s in avail)
        line_texts.append(txt)
        usable.append(li)

    # Sliding window over usable lines
    for start in range(len(line_texts)):
        buf = ""
        for end in range(start, len(line_texts)):
            if buf:
                buf += " "
            buf += line_texts[end]
            if _norm(buf) and norm_target in _norm(buf):
                return [block[usable[i]] for i in range(start, end + 1)]
            if len(_norm(buf)) > len(norm_target) * 3:
                break
    return None


def _find_matching_lines_cross_block(
    blocks: list[_Block], target: str, claimed: set[int],
) -> list[_Line] | None:
    """Fallback: match *target* across adjacent blocks.

    Summary paragraphs and skills sections are sometimes split into
    multiple PDF text blocks.  This joins adjacent blocks and retries.
    """
    norm_target = _norm(target)
    if not norm_target:
        return None

    for start_b in range(len(blocks)):
        lines_acc: list[_Line] = []
        buf = ""
        for end_b in range(start_b, min(start_b + 6, len(blocks))):
            for line in blocks[end_b]:
                avail = [s for s in line if id(s) not in claimed]
                if not avail:
                    continue
                txt = " ".join(s.get("text", "") for s in avail)
                if buf:
                    buf += " "
                buf += txt
                lines_acc.append(line)

            norm_buf = _norm(buf)
            if norm_buf and norm_target in norm_buf:
                return lines_acc
            if len(norm_buf) > len(norm_target) * 3:
                break

    return None


# ---------------------------------------------------------------------------
# Line-aware text insertion
# ---------------------------------------------------------------------------

def _line_info(line: _Line) -> tuple[float, float, float, float, str, float]:
    """Return (x0, y_baseline, width, height, orig_font_name, fontsize) for a line."""
    rects = [fitz.Rect(s["bbox"]) for s in line]
    x0 = min(r.x0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y0 = min(r.y0 for r in rects)
    y1 = max(r.y1 for r in rects)

    # Use span "origin" for the true baseline (more accurate than bbox bottom)
    # PyMuPDF provides origin = (x, baseline_y) on each span
    origins = [s.get("origin") for s in line if s.get("origin")]
    if origins:
        baseline = max(o[1] for o in origins)
    else:
        baseline = y1  # fallback to bbox bottom

    # Dominant font/size by character count
    size_c: Counter[float] = Counter()
    font_c: Counter[str] = Counter()
    for s in line:
        w = len(s.get("text", ""))
        size_c[s.get("size", 11)] += w
        font_c[s.get("font", "")] += w

    # If line mixes Bold and non-Bold variants of the same family,
    # prefer the Regular variant — we can't know which words in the
    # replacement text should be bold, and Bold glyphs are wider
    # (causing unwanted auto-shrink).  Purely-bold lines (headings)
    # are left as-is.
    font_names = set(font_c.keys())
    has_bold = any("Bold" in f or "bold" in f for f in font_names)
    has_nonbold = any("Bold" not in f and "bold" not in f for f in font_names)
    if has_bold and has_nonbold:
        nonbold = {f: c for f, c in font_c.items()
                   if "Bold" not in f and "bold" not in f}
        fontname = max(nonbold, key=nonbold.get) if nonbold else font_c.most_common(1)[0][0]
    else:
        fontname = font_c.most_common(1)[0][0]
    fontsize = size_c.most_common(1)[0][0]

    return x0, baseline, x1 - x0, y1 - y0, fontname, fontsize


def _colour(line: _Line) -> tuple[float, float, float]:
    c = line[0].get("color", 0)
    return (((c >> 16) & 0xFF) / 255.0,
            ((c >> 8) & 0xFF) / 255.0,
            (c & 0xFF) / 255.0)


def _wrap_text_to_lines(text: str, font: fitz.Font, fontsize: float,
                        widths: list[float]) -> list[str]:
    """Word-wrap *text* so each piece fits in the corresponding width.

    Uses exact font metrics from the actual embedded font.
    If there are more words than fit, the last line gets the remainder.
    If there are fewer words than lines, trailing lines are empty strings.
    """
    words = text.split()
    result: list[str] = []
    wi = 0  # word index

    for i, max_w in enumerate(widths):
        line = ""
        while wi < len(words):
            candidate = f"{line} {words[wi]}".strip() if line else words[wi]
            tw = font.text_length(candidate, fontsize=fontsize)
            if tw > max_w and line:
                break           # this word doesn't fit — move to next line
            line = candidate
            wi += 1
        result.append(line)

    # If words remain, append them to the last line
    if wi < len(words) and result:
        result[-1] = f"{result[-1]} {' '.join(words[wi:])}".strip()

    # Pad with empty strings if fewer words than lines
    while len(result) < len(widths):
        result.append("")

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rewrite_pdf(file_bytes: bytes, resume: ResumeData) -> bytes:
    if not resume.replacements:
        logger.warning("No replacements — returning original PDF.")
        return file_bytes

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    font_cache = _build_font_cache(doc)
    real = [r for r in resume.replacements if r.old and r.new and r.old != r.new]
    total_matched = 0

    for page_idx, page in enumerate(doc):
        blocks = _collect_blocks(page)
        claimed: set[int] = set()

        # (matched_lines, new_text)
        ops: list[tuple[list[_Line], str]] = []

        for repl in real:
            matched_lines = None
            for block in blocks:
                matched_lines = _find_matching_lines(block, repl.old, claimed)
                if matched_lines:
                    break
            # Cross-block fallback for summary/skills paragraphs that
            # span multiple PDF text blocks.
            if not matched_lines:
                matched_lines = _find_matching_lines_cross_block(
                    blocks, repl.old, claimed,
                )
            if matched_lines:
                ops.append((matched_lines, _sanitize_text(repl.new)))
                for line in matched_lines:
                    claimed.update(id(s) for s in line)
                total_matched += 1
            else:
                logger.debug("p%d: no match '%s…'", page_idx, repl.old[:50])

        if not ops:
            continue

        # ── Phase 1: redact matched areas ────────────────────────────────
        # Per-line rects from content spans only (preserves bullet markers).
        # White fill ensures clean removal of old glyphs; per-line rects are
        # tight enough to avoid covering decorative graphics nearby.
        for matched_lines, _ in ops:
            for line in matched_lines:
                content = _content_spans(line)
                if not content:
                    continue
                line_rect = fitz.Rect()
                for span in content:
                    line_rect |= fitz.Rect(span["bbox"])
                page.add_redact_annot(line_rect, fill=(1, 1, 1))

        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_IMAGE_NONE,
        )

        # ── Phase 2: insert replacement text via TextWriter ──────────────
        # Group ops by colour so each TextWriter gets a uniform colour
        colour_ops: dict[tuple, list[tuple[list[_Line], str]]] = {}
        for matched_lines, new_text in ops:
            c = _colour(matched_lines[0])
            colour_ops.setdefault(c, []).append((matched_lines, new_text))

        for colour, c_ops in colour_ops.items():
            tw = fitz.TextWriter(page.rect)

            for matched_lines, new_text in c_ops:
                # Use content spans (skip bullet markers) for positioning
                content_lines = [_content_spans(ln) or ln for ln in matched_lines]
                infos = [_line_info(cl) for cl in content_lines]

                # Resolve font per line (different lines may have different fonts)
                def _resolve_font(orig_name: str, text: str = "") -> fitz.Font:
                    f = font_cache.get(orig_name)
                    if f is None:
                        clean = orig_name.split("+", 1)[-1] if "+" in orig_name else orig_name
                        f = font_cache.get(clean)
                    # Verify the font can render every character in the text
                    if f is not None and text and not _font_can_render(f, text):
                        logger.warning(
                            "Font '%s' missing glyphs for replacement — using fallback",
                            orig_name,
                        )
                        f = None
                    if f is None:
                        b14 = _base14_name(content_lines[0][0])
                        f = fitz.Font(b14)
                        logger.warning("Font '%s' not found — falling back to %s", orig_name, b14)
                    return f

                primary_font = _resolve_font(infos[0][4], new_text)
                primary_size = infos[0][5]

                if len(content_lines) >= 2:
                    # ── Multi-line (summary / skills paragraph) ──────────
                    # Use fill_textbox for natural word-wrapping within the
                    # original rectangular area instead of per-line insertion.
                    union_rect = fitz.Rect()
                    for cl in content_lines:
                        for s in cl:
                            union_rect |= fitz.Rect(s["bbox"])

                    x0_first = infos[0][0]
                    baseline_first = infos[0][1]

                    # Pre-compute fontsize that fits using a scratch TextWriter
                    sz = primary_size
                    for _ in range(8):
                        probe = fitz.TextWriter(page.rect)
                        excess = probe.fill_textbox(
                            union_rect, new_text,
                            pos=fitz.Point(x0_first, baseline_first),
                            font=primary_font, fontsize=sz,
                        )
                        if not excess:
                            break
                        sz *= 0.95

                    tw.fill_textbox(
                        union_rect, new_text,
                        pos=fitz.Point(x0_first, baseline_first),
                        font=primary_font, fontsize=sz,
                    )
                else:
                    # ── Single line (bullet points) ──────────────────────
                    widths = [info[2] for info in infos]
                    wrap_width = max(widths) if widths else 0
                    wrap_widths = [wrap_width] * len(widths)

                    sz = primary_size
                    for _ in range(8):
                        wrapped = _wrap_text_to_lines(
                            new_text, primary_font, sz, wrap_widths,
                        )
                        overflow = any(
                            lt and primary_font.text_length(lt, fontsize=sz) > w * 1.02
                            for lt, w in zip(wrapped, wrap_widths)
                        )
                        if not overflow:
                            break
                        sz *= 0.95

                    for line_text, info in zip(wrapped, infos):
                        if not line_text:
                            continue
                        x0, baseline, w, h, fn, _fs = info
                        font = _resolve_font(fn, line_text)

                        tw.append(
                            fitz.Point(x0, baseline),
                            line_text,
                            font=font,
                            fontsize=sz,
                        )

            tw.write_text(page, color=colour)

    logger.info("Rewriter: matched %d / %d replacements.", total_matched, len(real))
    if total_matched == 0:
        logger.warning("ZERO matches — returning original PDF.")
        doc.close()
        return file_bytes

    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    doc.close()
    return buf.getvalue()
