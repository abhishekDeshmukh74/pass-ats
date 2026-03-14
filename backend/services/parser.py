import base64
import fitz  # PyMuPDF


def parse_pdf(file_bytes: bytes) -> tuple[str, str, str, str]:
    """Extract plain text and styled HTML from PDF bytes using PyMuPDF.

    The HTML output preserves font family, size, colour, bold/italic and
    absolute position for every text span on every page, giving an exact
    visual replica of the original document.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text_parts: list[str] = []
    html_pages: list[str] = []
    for i, page in enumerate(doc):
        text_parts.append(page.get_text("text"))
        page_html = page.get_text("html")
        html_pages.append(
            f'<div class="pdf-page" id="page-{i + 1}" '
            f'style="position:relative;margin-bottom:24px;">{page_html}</div>'
        )
    doc.close()
    text = "\n".join(text_parts)
    html = (
        '<div class="pdf-document" '
        'style="font-family:sans-serif;background:#f4f4f4;padding:16px;">'
        + "\n".join(html_pages)
        + "</div>"
    )
    return text, html, base64.b64encode(file_bytes).decode(), "pdf"
