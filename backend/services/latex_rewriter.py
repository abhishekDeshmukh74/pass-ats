"""
latex_rewriter.py — Apply AI text replacements to a .tex source and compile
                    it to PDF using xelatex (falls back to pdflatex/lualatex).

Flow:
  1. Decode the original .tex source from bytes.
  2. For each TextReplacement(old, new): replace the first occurrence of
     'old' in the source (the AI generates 'old' values that are verbatim
     substrings of the source text).
  3. Write the patched source to a temp directory.
  4. Invoke xelatex twice (first pass lays out, second resolves references).
  5. Return the compiled PDF bytes.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata

from backend.models import ResumeData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text sanitisation
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


def _sanitize(text: str) -> str:
    """Normalise replacement text to safe Unicode."""
    return unicodedata.normalize("NFKC", text).translate(_OUTPUT_CHAR_MAP)


def _latex_escape(text: str) -> str:
    r"""Escape bare %% and & in plain text to their LaTeX equivalents (\\%% and \\&)."""
    text = re.sub(r"(?<!\\)%", r"\\%", text)
    text = re.sub(r"(?<!\\)&", r"\\&", text)
    return text


# Characters that _strip_latex converts from \X → X in plain text.
_LATEX_SPECIAL_CHARS = frozenset("%&$#_")


def _build_flexible_pattern(plain_text: str) -> str:
    """Build a regex from *plain_text* that tolerates .tex line-wrapping
    (whitespace differences) and optional LaTeX backslash escapes before
    special characters (``\\%``, ``\\&``, etc.).

    This lets us find the AI's single-line plain-text ``old`` string inside
    the original ``.tex`` source even when the source wraps long lines with
    newlines + indentation.
    """
    parts: list[str] = []
    i = 0
    while i < len(plain_text):
        ch = plain_text[i]
        if ch in (" ", "\t", "\n", "\r"):
            # Consume consecutive whitespace, emit flexible \s+
            while i < len(plain_text) and plain_text[i] in (" ", "\t", "\n", "\r"):
                i += 1
            parts.append(r"\s+")
        elif ch in _LATEX_SPECIAL_CHARS:
            # Allow an optional preceding backslash (\% vs %)
            parts.append(r"\\?" + re.escape(ch))
            i += 1
        else:
            parts.append(re.escape(ch))
            i += 1
    return "".join(parts)


# Inline LaTeX formatting commands whose content becomes plain text.
_INLINE_CMDS_RE = re.compile(
    r"\\(?:textbf|textit|texttt|textrm|textsf|emph|underline|strong)\{([^}]*)\}"
)
# LaTeX special-character escapes: \%, \&, \$, \#, \_
_LATEX_SPECIAL_RE = re.compile(r"\\([%&$#_])")


def _strip_formatting(tex: str) -> tuple[str, list[int]]:
    """Strip inline LaTeX formatting from *tex*, returning the plain text and
    a position map from plain-text indices back to original source indices.

    The position map ``pos_map`` has ``len(plain) + 1`` entries where
    ``pos_map[i]`` is the index in *tex* corresponding to ``plain[i]``.
    """
    # Multi-pass: keep stripping until no more formatting commands remain
    source = tex
    pos_map = list(range(len(source) + 1))

    for _ in range(5):  # Max nesting depth
        new_source: list[str] = []
        new_pos_map: list[int] = []
        last = 0
        found = False

        for m in _INLINE_CMDS_RE.finditer(source):
            found = True
            # Keep text before the match
            for j in range(last, m.start()):
                new_source.append(source[j])
                new_pos_map.append(pos_map[j])
            # Keep only the content inside braces (group 1)
            content_start = m.start(1)
            for j in range(content_start, m.end(1)):
                new_source.append(source[j])
                new_pos_map.append(pos_map[j])
            last = m.end()

        if not found:
            break

        # Append remaining text after the last match
        for j in range(last, len(source)):
            new_source.append(source[j])
            new_pos_map.append(pos_map[j])
        # Sentinel for end-of-string
        new_pos_map.append(pos_map[len(source)])

        source = "".join(new_source)
        pos_map = new_pos_map

    # Also strip \%, \& etc. → plain characters
    new_source2: list[str] = []
    new_pos_map2: list[int] = []
    last = 0
    for m in _LATEX_SPECIAL_RE.finditer(source):
        for j in range(last, m.start()):
            new_source2.append(source[j])
            new_pos_map2.append(pos_map[j])
        # Keep only the special char (group 1), map to original position
        new_source2.append(m.group(1))
        new_pos_map2.append(pos_map[m.start(1)])
        last = m.end()
    for j in range(last, len(source)):
        new_source2.append(source[j])
        new_pos_map2.append(pos_map[j])
    new_pos_map2.append(pos_map[len(source)])

    return "".join(new_source2), new_pos_map2


def _find_in_stripped(tex_source: str, plain_old: str) -> tuple[int, int] | None:
    """Find *plain_old* in *tex_source* by stripping LaTeX formatting first,
    then mapping the match positions back to the original source.

    Returns ``(start, end)`` indices in *tex_source*, or ``None``.
    """
    stripped, pos_map = _strip_formatting(tex_source)

    # Build a flexible pattern from plain_old that tolerates whitespace diffs
    pattern = _build_flexible_pattern(plain_old)
    m = re.search(pattern, stripped)
    if m:
        return pos_map[m.start()], pos_map[m.end()]
    return None


# ---------------------------------------------------------------------------
# Compiler detection
# ---------------------------------------------------------------------------

# Well-known MiKTeX / TeX Live installation directories (Windows + Linux/Mac)
_MIKTEX_HINTS = [
    r"C:\Users\{user}\AppData\Local\Programs\MiKTeX\miktex\bin\x64",
    r"C:\Program Files\MiKTeX\miktex\bin\x64",
    r"C:\Program Files (x86)\MiKTeX\miktex\bin",
    r"/usr/bin",
    r"/usr/local/bin",
    r"/Library/TeX/texbin",
]


def _find_compiler() -> str:
    """Return the full path to the first available LaTeX compiler."""
    import getpass

    # 1. Explicit override via environment variable
    override = os.environ.get("LATEX_COMPILER_PATH")
    if override and os.path.isfile(override):
        return override

    # 2. Standard PATH lookup
    for compiler in ("xelatex", "pdflatex", "lualatex"):
        found = shutil.which(compiler)
        if found:
            return found

    # 3. Probe known install locations (handles MiKTeX user install
    #    whose PATH update only takes effect in a new login shell,
    #    not in a long-running uvicorn process)
    try:
        username = getpass.getuser()
    except Exception:
        username = ""

    for hint in _MIKTEX_HINTS:
        hint = hint.replace("{user}", username)
        for compiler in ("xelatex", "pdflatex", "lualatex"):
            for ext in (".exe", ""):
                candidate = os.path.join(hint, compiler + ext)
                if os.path.isfile(candidate):
                    return candidate

    raise RuntimeError(
        "No LaTeX compiler found. "
        "Install MiKTeX (https://miktex.org) or TeX Live and ensure "
        "`xelatex` is on your PATH, or set the LATEX_COMPILER_PATH env var."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rewrite_tex(tex_bytes: bytes, resume: ResumeData) -> bytes:
    """Apply AI replacements to .tex source and return compiled PDF bytes."""
    real = [r for r in resume.replacements if r.old and r.new and r.old != r.new]

    tex_source = tex_bytes.decode("utf-8", errors="replace")
    total_matched = 0

    for repl in real:
        new_text = _latex_escape(_sanitize(repl.new))
        if repl.old in tex_source:
            tex_source = tex_source.replace(repl.old, new_text, 1)
            total_matched += 1
        else:
            # Fallback 1 (forward-compat): AI was given fixed plain text where
            # \% appeared as %; re-escape % → \% to find the match in source.
            escaped_old = _latex_escape(repl.old)
            # Fallback 2 (backward-compat): broken parser stripped \%  as a
            # comment, leaving a bare \ in the plain text. Restore \% so the
            # old string matches the original source.
            restored_old = re.sub(r"\\(?=[^a-zA-Z*{\\]|$)", r"\\%", repl.old)

            if escaped_old != repl.old and escaped_old in tex_source:
                tex_source = tex_source.replace(escaped_old, new_text, 1)
                total_matched += 1
                logger.debug("LaTeX rewriter: matched via %% escape for '%s…'", repl.old[:60])
            elif restored_old != repl.old and restored_old in tex_source:
                # Mirror the same \% restoration in new_text so the LaTeX
                # group structure (e.g. closing }) is preserved correctly.
                restored_new = re.sub(r"\\(?=[^a-zA-Z*{\\]|$)", r"\\%", new_text)
                tex_source = tex_source.replace(restored_old, restored_new, 1)
                total_matched += 1
                logger.debug("LaTeX rewriter: matched via \\%% restore for '%s…'", repl.old[:60])
            else:
                # Fallback 3 (flexible): handle .tex line-wrapping (newlines
                # + indentation where the plain text has a single space) and
                # optional LaTeX backslash escapes (\%, \&, etc.).
                pattern = _build_flexible_pattern(repl.old)
                m = re.search(pattern, tex_source)
                if m:
                    tex_source = tex_source[:m.start()] + new_text + tex_source[m.end():]
                    total_matched += 1
                    logger.debug("LaTeX rewriter: matched via flexible pattern for '%s…'", repl.old[:60])
                else:
                    # Fallback 4 (formatting-aware): strip inline LaTeX
                    # formatting (\textbf{...}, \textit{...}, etc.) from the
                    # source, match against the plain-text form, then map
                    # positions back to the original source.
                    span = _find_in_stripped(tex_source, repl.old)
                    if span:
                        start, end = span
                        tex_source = tex_source[:start] + new_text + tex_source[end:]
                        total_matched += 1
                        logger.debug("LaTeX rewriter: matched via formatting-stripped search for '%s…'", repl.old[:60])
                    else:
                        logger.debug("LaTeX rewriter: no match for '%s…'", repl.old[:60])

    logger.info(
        "LaTeX rewriter: matched %d / %d replacements.",
        total_matched, len(real),
    )

    return _compile(tex_source)


def _tlmgr_install(packages: list[str]) -> None:
    """Attempt to install *packages* via tlmgr (TeX Live package manager).

    Tries user-mode first (no sudo required); falls back to system-mode.
    If tlmgr itself needs updating (exit 255 + "needs to be updated"), runs
    ``tlmgr update --self`` first then retries.
    Silently skips if tlmgr is not found.
    """
    tlmgr = shutil.which("tlmgr")
    if not tlmgr:
        logger.warning("tlmgr not found; cannot auto-install packages: %s", packages)
        return

    def _run(args: list[str]) -> "subprocess.CompletedProcess[bytes]":
        return subprocess.run(args, capture_output=True, timeout=120)

    def _needs_self_update(result: "subprocess.CompletedProcess[bytes]") -> bool:
        out = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        return result.returncode == 255 and "needs to be updated" in out

    for mode_flag in (["--usermode"], []):
        try:
            result = _run([tlmgr, "install", *mode_flag, *packages])
            # tlmgr itself may be outdated; update self then retry once
            if _needs_self_update(result):
                logger.info("Updating tlmgr itself before installing packages.")
                _run([tlmgr, "update", *mode_flag, "--self"])
                result = _run([tlmgr, "install", *mode_flag, *packages])
            if result.returncode == 0:
                logger.info(
                    "tlmgr installed packages %s (mode=%s)",
                    packages,
                    "user" if mode_flag else "system",
                )
                return
            # user-mode may fail if not initialised; try system mode next
            logger.debug("tlmgr %s exit %d", mode_flag, result.returncode)
        except Exception as exc:
            logger.debug("tlmgr attempt failed: %s", exc)
    logger.warning("Failed to auto-install LaTeX packages via tlmgr: %s", packages)


def _missing_packages(log_output: str) -> list[str]:
    """Extract package names from 'File `foo.sty' not found' errors."""
    return re.findall(r"File `([^']+?)\.sty' not found", log_output)


def _compile(tex_source: str) -> bytes:
    """Write *tex_source* to a temp dir, run xelatex twice, return PDF bytes."""
    compiler = _find_compiler()
    logger.info("Compiling LaTeX with %s", compiler)

    # XeTeX uses fontspec for font handling; fontenc with T1 encoding
    # causes "Corrupted NFSS tables" errors.  Replace fontenc with fontspec
    # when compiling with xelatex.
    compiler_basename = os.path.basename(compiler).lower()
    if "xelatex" in compiler_basename:
        tex_source = re.sub(
            r"\\usepackage\s*(\[[^\]]*\])?\s*\{fontenc\}",
            r"\\usepackage{fontspec}",
            tex_source,
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "resume.tex")
        with open(tex_path, "w", encoding="utf-8") as fh:
            fh.write(tex_source)

        # MiKTeX supports --enable-installer to auto-fetch missing packages.
        # TeX Live ignores unknown options less gracefully, so only add it
        # when we can positively identify MiKTeX by the compiler path.
        is_miktex = "miktex" in compiler.lower()
        compile_args = [
            compiler,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={tmpdir}",
        ]
        if is_miktex:
            compile_args.append("--enable-installer")
        compile_args.append(tex_path)

        last_result = None
        auto_installed = False
        for pass_num in range(1, 3):  # two passes for cross-refs / TOC
            last_result = subprocess.run(
                compile_args,
                capture_output=True,
                timeout=120,
                cwd=tmpdir,
            )
            logger.debug(
                "xelatex pass %d exit code: %d", pass_num, last_result.returncode,
            )
            # On the first pass, detect and auto-install missing packages then
            # re-run rather than surfacing the error immediately.
            if pass_num == 1 and last_result.returncode != 0 and not auto_installed:
                combined = (
                    last_result.stdout.decode("utf-8", errors="replace")
                    + last_result.stderr.decode("utf-8", errors="replace")
                )
                missing = _missing_packages(combined)
                if missing:
                    logger.info("Auto-installing missing LaTeX packages: %s", missing)
                    _tlmgr_install(missing)
                    auto_installed = True
                    # Redo both passes after installing packages
                    for retry_pass in range(1, 3):
                        last_result = subprocess.run(
                            compile_args,
                            capture_output=True,
                            timeout=120,
                            cwd=tmpdir,
                        )
                        logger.debug(
                            "xelatex retry pass %d exit code: %d",
                            retry_pass,
                            last_result.returncode,
                        )
                    break  # exit outer loop; retry loop handled both passes

        pdf_path = os.path.join(tmpdir, "resume.pdf")
        if not os.path.exists(pdf_path):
            assert last_result is not None
            stderr = last_result.stderr.decode("utf-8", errors="replace")
            stdout = last_result.stdout.decode("utf-8", errors="replace")
            # Surface the last ~40 lines of output for diagnosis
            log_tail = "\n".join((stdout + "\n" + stderr).splitlines()[-40:])
            raise RuntimeError(
                f"LaTeX compilation failed (compiler: {compiler}).\n{log_tail}"
            )

        with open(pdf_path, "rb") as fh:
            return fh.read()
