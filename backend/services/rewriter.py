"""
rewriter.py — Replace text content in an original PDF resume while preserving
all formatting (fonts, colours, layout) intact.

Strategy using PyMuPDF (fitz):
  1. Use page.search_for() to locate each replacement target in the PDF.
  2. Capture font name, size, and colour from the text span at that location.
  3. Redact the found region via page.add_redact_annot() / apply_redactions().
  4. Re-insert the new text with matched styling via fitz.TextWriter.
"""

from __future__ import annotations

import io
import logging
import unicodedata

import fitz  # PyMuPDF

from backend.models import ResumeData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_OUTPUT_CHAR_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",             # smart single quotes
    "\u201c": '"', "\u201d": '"',             # smart double quotes
    "\u2013": "-", "\u2014": "-",             # en/em dash
    "\u2026": "...",                           # ellipsis
    "\u00a0": " ",                             # non-breaking space
    "\u200b": "", "\u200c": "", "\u200d": "",  # zero-width chars
    "\ufeff": "",                              # BOM
})


def _sanitize_text(text: str) -> str:
    """Normalise text to characters that most PDF fonts can render."""
    return unicodedata.normalize("NFKC", text).translate(_OUTPUT_CHAR_MAP)


def _search_text(page: fitz.Page, text: str) -> list[fitz.Rect]:
    """Search for *text* on *page*, falling back to a sanitised variant."""
    rects = page.search_for(text)
    if rects:
        return rects
    sanitized = _sanitize_text(text)
    if sanitized != text:
        return page.search_for(sanitized)
    return []


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

# Maps lower-cased base-14 PDF font names to PyMuPDF built-in abbreviations.
_BASE14: dict[str, str] = {
    "helvetica":             "helv",
    "helvetica-bold":        "hebo",
    "helvetica-oblique":     "heob",
    "helvetica-boldoblique": "hebi",
    "times-roman":           "tiro",
    "times-bold":            "tibo",
    "times-italic":          "tiit",
    "times-bolditalic":      "tibi",
    "courier":               "cour",
    "courier-bold":          "cobo",
    "courier-oblique":       "coit",
    "courier-boldoblique":   "cobi",
}

_BOLD_FLAG   = 1 << 4   # span["flags"] bit 4
_ITALIC_FLAG = 1 << 1   # span["flags"] bit 1

_FLAG_FALLBACK: dict[tuple[bool, bool], str] = {
    (True,  True):  "tibi",
    (True,  False): "tibo",
    (False, True):  "tiit",
    (False, False): "tiro",
}


def _build_font_map(doc: fitz.Document, page: fitz.Page) -> dict[str, fitz.Font]:
    """Return {font_name: fitz.Font} for every font embedded in *page*."""
    font_map: dict[str, fitz.Font] = {}
    for info in page.get_fonts(full=True):
        xref     = info[0]
        basename = info[3]
        name     = info[4]
        try:
            raw        = doc.extract_font(xref)
            font_bytes = raw[3] if raw and len(raw) > 3 else None
            if font_bytes:
                font_obj = fitz.Font(fontbuffer=font_bytes)
                for key in (basename, name):
                    if key:
                        font_map[key] = font_obj
                # Strip subset prefix: "ABCDEF+Arial-Bold" → "Arial-Bold"
                if "+" in basename:
                    font_map[basename.split("+", 1)[1]] = font_obj
        except Exception:
            pass
    return font_map


def _resolve_font(
    fname: str, flags: int, font_map: dict[str, fitz.Font],
) -> fitz.Font:
    """Best available fitz.Font for a span with the given name and flags."""
    # 1. Try embedded font (with or without subset prefix)
    font = font_map.get(fname)
    if font is None and "+" in fname:
        font = font_map.get(fname.split("+", 1)[1])
    if font is not None:
        return font

    # 2. Try base-14 font identified by name
    fitz_name = _BASE14.get(fname.lower())
    if fitz_name:
        return fitz.Font(fitz_name)

    # 3. Fallback based on bold/italic flags
    return fitz.Font(_FLAG_FALLBACK[(
        bool(flags & _BOLD_FLAG),
        bool(flags & _ITALIC_FLAG),
    )])


def _get_style(
    page: fitz.Page, rect: fitz.Rect, font_map: dict[str, fitz.Font],
) -> dict:
    """Return font, fontsize (pt), and RGB colour for the text at *rect*."""
    try:
        for block in page.get_text("dict", clip=rect).get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    fname  = span.get("font", "")
                    size   = float(span.get("size", 11.0))
                    c      = int(span.get("color", 0))
                    color  = (
                        (c >> 16 & 0xFF) / 255.0,
                        (c >>  8 & 0xFF) / 255.0,
                        (c       & 0xFF) / 255.0,
                    )
                    flags  = int(span.get("flags", 0))
                    font   = _resolve_font(fname, flags, font_map)
                    return {"font": font, "fontsize": size, "color": color}
    except Exception:
        pass
    return {"font": fitz.Font("helv"), "fontsize": 11.0, "color": (0.0, 0.0, 0.0)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rewrite_pdf(file_bytes: bytes, resume: ResumeData) -> bytes:
    real = [r for r in resume.replacements if r.old and r.new and r.old != r.new]
    if not real:
        logger.warning("No replacements — returning original PDF.")
        return file_bytes

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    total_matched = 0

    for page in doc:
        font_map = _build_font_map(doc, page)

        # Collect everything to do on this page BEFORE modifying it.
        # pending: (insert_rect, new_text, style)
        pending: list[tuple[fitz.Rect, str, dict]] = []

        for repl in real:
            rects = _search_text(page, repl.old)
            if not rects:
                logger.debug("p%d: no match for '%s…'", page.number, repl.old[:50])
                continue

            new_text = _sanitize_text(repl.new)
            style    = _get_style(page, rects[0], font_map)

            # Redact every rect belonging to this match (handles line-wrapping).
            for rect in rects:
                page.add_redact_annot(rect)

            # Re-insert new text once, at the first (topmost) rect.
            pending.append((rects[0], new_text, style))
            total_matched += 1

        if pending:
            page.apply_redactions()
            for rect, new_text, style in pending:
                tw = fitz.TextWriter(page.rect)
                # rect.y1 = visual bottom of the bounding box ≈ text baseline
                tw.append(
                    fitz.Point(rect.x0, rect.y1),
                    new_text,
                    font=style["font"],
                    fontsize=style["fontsize"],
                )
                tw.write_text(page, color=style["color"])

    logger.info("Rewriter: matched %d / %d replacements.", total_matched, len(real))
    if total_matched == 0:
        logger.warning("ZERO matches — returning original PDF.")
        return file_bytes

    buf = io.BytesIO()
    doc.save(buf, garbage=4, deflate=True)
    return buf.getvalue()
