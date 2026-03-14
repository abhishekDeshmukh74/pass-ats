"""
latex_parser.py — Extract plain text from a .tex resume for the AI pipeline.

The raw LaTeX source is preserved as b64 for later rewriting.
Plain text is produced by stripping LaTeX commands so the AI reads
natural language, while the verbatim strings it picks for 'old' replacements
still exist as substrings in the original source.
"""

from __future__ import annotations

import base64
import re


# ---------------------------------------------------------------------------
# LaTeX → plain text
# ---------------------------------------------------------------------------

def _strip_latex(source: str) -> str:
    """Best-effort conversion of LaTeX markup to readable plain text."""
    # Remove comments — use negative lookbehind so \% (literal percent) is preserved
    text = re.sub(r"(?<!\\)%.*$", "", source, flags=re.MULTILINE)

    # Convert LaTeX special-character escapes → readable text BEFORE the generic
    # backslash-command stripper runs (\%, \& etc. are not alpha-commands).
    for _latex_seq, _plain in (
        (r"\%", "%"), (r"\&", "&"), (r"\$", "$"), (r"\#", "#"), (r"\_", "_"),
    ):
        text = text.replace(_latex_seq, _plain)

    # \href{url}{display} → display
    text = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", text)

    # Formatting wrappers: \textbf{x}, \textit{x}, \emph{x}, etc. → x
    text = re.sub(
        r"\\(?:textbf|textit|texttt|textrm|textsf|emph|underline|strong)\{([^}]*)\}",
        r"\1", text,
    )

    # Section-like commands: \section{Title} → Title
    text = re.sub(
        r"\\(?:section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^}]*)\}",
        r"\1\n", text,
    )

    # \item bullet marker
    text = re.sub(r"\\item\b\s*", "\n• ", text)

    # \\ line break → newline
    text = text.replace("\\\\", "\n")

    # Remove \begin{...} / \end{...} wrappers (keep content)
    text = re.sub(r"\\(?:begin|end)\{[^}]*\}", "", text)

    # Remove \name{x}, \address{x}, \phone{x} etc. → x
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)

    # Remove remaining backslash commands
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)

    # Remove stray braces
    text = re.sub(r"[{}]", "", text)

    # Normalise whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_tex(file_bytes: bytes) -> tuple[str, str, str, str]:
    """Parse a .tex resume file.

    Returns:
        (plain_text, html_preview, b64_source, "tex")

    plain_text  — LaTeX-stripped text fed to the AI pipeline.
    html_preview — monospace preview of the raw source for the UI.
    b64_source  — base64-encoded original .tex bytes (used by the rewriter).
    """
    tex_source = file_bytes.decode("utf-8", errors="replace")

    # Extract document body where resume content lives
    body_match = re.search(
        r"\\begin\{document\}(.*?)\\end\{document\}", tex_source, re.DOTALL,
    )
    body = body_match.group(1) if body_match else tex_source

    plain_text = _strip_latex(body)

    # HTML preview: syntax-highlighted monospace block
    esc = (
        tex_source.replace("&", "&amp;")
                  .replace("<", "&lt;")
                  .replace(">", "&gt;")
    )
    html = (
        '<div class="pdf-document" '
        'style="font-family:sans-serif;background:#f4f4f4;padding:16px;">'
        '<div class="pdf-page" id="page-1" '
        'style="background:#fff;padding:32px;margin-bottom:24px;'
        'overflow-x:auto;">'
        '<pre style="font-family:\'Courier New\',monospace;font-size:12px;'
        'white-space:pre-wrap;word-break:break-word;margin:0;">'
        f"{esc}</pre></div></div>"
    )

    return plain_text, html, base64.b64encode(file_bytes).decode(), "tex"
