import io
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    HRFlowable,
    KeepTogether,
)
from reportlab.lib.enums import TA_CENTER
from backend.models import ResumeData

ACCENT = colors.HexColor("#1a56db")
LINK_COLOR = "#1a56db"
TEXT_DARK = colors.HexColor("#111827")
TEXT_MID = colors.HexColor("#374151")
TEXT_SOFT = colors.HexColor("#6b7280")
RULE_COLOR = colors.HexColor("#d1d5db")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "name", parent=base["Normal"],
            fontSize=20, leading=24, textColor=TEXT_DARK,
            alignment=TA_CENTER, spaceAfter=3, fontName="Helvetica-Bold",
        ),
        "contact": ParagraphStyle(
            "contact", parent=base["Normal"],
            fontSize=9, leading=13, alignment=TA_CENTER,
            textColor=TEXT_SOFT, spaceAfter=6,
        ),
        "section_heading": ParagraphStyle(
            "section_heading", parent=base["Normal"],
            fontSize=10, leading=13, textColor=ACCENT,
            spaceBefore=8, spaceAfter=2, fontName="Helvetica-Bold",
        ),
        "job_title": ParagraphStyle(
            "job_title", parent=base["Normal"],
            fontSize=10, leading=13, fontName="Helvetica-Bold",
            textColor=TEXT_DARK, spaceAfter=0,
        ),
        "job_company": ParagraphStyle(
            "job_company", parent=base["Normal"],
            fontSize=9, leading=12, textColor=TEXT_MID, spaceAfter=1,
        ),
        "meta": ParagraphStyle(
            "meta", parent=base["Normal"],
            fontSize=8.5, leading=11, textColor=TEXT_SOFT, spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=base["Normal"],
            fontSize=9, leading=12.5, textColor=TEXT_MID,
            leftIndent=10, firstLineIndent=-8, spaceAfter=1,
        ),
        "summary": ParagraphStyle(
            "summary", parent=base["Normal"],
            fontSize=9, leading=13.5, textColor=TEXT_MID, spaceAfter=4,
        ),
        "skills_body": ParagraphStyle(
            "skills_body", parent=base["Normal"],
            fontSize=9, leading=13, textColor=TEXT_MID, spaceAfter=2,
        ),
    }


def _rule(elements: list) -> None:
    elements.append(
        HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR, spaceAfter=4, spaceBefore=2)
    )


def _safe_xml(text: str) -> str:
    """Escape special XML characters so ReportLab Paragraph doesn't choke."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(href: str, label: str) -> str:
    """Return a ReportLab XML anchor tag with blue color."""
    safe_label = _safe_xml(label)
    safe_href = href.replace("&", "&amp;")
    return f'<a href="{safe_href}" color="{LINK_COLOR}">{safe_label}</a>'


def _contact_line(resume: ResumeData) -> str:
    """Build the contact info line with blue clickable links."""
    parts = []
    if resume.phone:
        parts.append(_safe_xml(resume.phone))
    if resume.email:
        parts.append(_link(f"mailto:{resume.email}", resume.email))
    if resume.location:
        parts.append(_safe_xml(resume.location))
    if resume.linkedin:
        url = resume.linkedin if resume.linkedin.startswith("http") else f"https://{resume.linkedin}"
        parts.append(_link(url, resume.linkedin))
    if resume.github:
        url = resume.github if resume.github.startswith("http") else f"https://{resume.github}"
        parts.append(_link(url, resume.github))
    return "  \u2022  ".join(parts)


def _bullet_para(text: str, st: dict) -> Paragraph:
    return Paragraph(f"\u2022\u2002{_safe_xml(text)}", st["bullet"])


def generate_pdf(resume: ResumeData) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=resume.name,
        author=resume.name,
    )
    st = _styles()
    elements: list = []

    # ── Header ──────────────────────────────────────────────────────────────────
    elements.append(Paragraph(_safe_xml(resume.name), st["name"]))
    contact = _contact_line(resume)
    if contact:
        elements.append(Paragraph(contact, st["contact"]))
    _rule(elements)

    # ── Summary ─────────────────────────────────────────────────────────────────
    if resume.summary:
        elements.append(Paragraph("PROFESSIONAL SUMMARY", st["section_heading"]))
        _rule(elements)
        elements.append(Paragraph(_safe_xml(resume.summary), st["summary"]))

    # ── Experience ──────────────────────────────────────────────────────────────
    if resume.experience:
        elements.append(Paragraph("EXPERIENCE", st["section_heading"]))
        _rule(elements)
        for exp in resume.experience:
            block = []
            # Title row
            dates = f"{_safe_xml(exp.start_date)} \u2013 {_safe_xml(exp.end_date)}"
            title_xml = (
                f'<para>'
                f'<b>{_safe_xml(exp.job_title)}</b>'
                f'<fontSize size="8.5"> &nbsp;&nbsp;|&nbsp;&nbsp; </fontSize>'
                f'{_safe_xml(exp.company)}'
                f'<fontSize size="8.5"> &nbsp;&nbsp;|&nbsp;&nbsp; </fontSize>'
                f'<font color="{LINK_COLOR}">{dates}</font>'
                f'</para>'
            )
            # Use two separate paragraphs instead of inline <para>
            header_text = (
                f'<b>{_safe_xml(exp.job_title)}</b>'
            )
            block.append(Paragraph(header_text, st["job_title"]))
            meta_parts = [_safe_xml(exp.company)]
            if exp.location:
                meta_parts.append(_safe_xml(exp.location))
            meta_parts.append(dates)
            block.append(Paragraph("  \u2022  ".join(meta_parts), st["meta"]))
            for b in exp.bullets:
                block.append(_bullet_para(b, st))
            block.append(Spacer(1, 5))
            elements.append(KeepTogether(block))

    # ── Education ───────────────────────────────────────────────────────────────
    if resume.education:
        elements.append(Paragraph("EDUCATION", st["section_heading"]))
        _rule(elements)
        for edu in resume.education:
            block = []
            block.append(Paragraph(f"<b>{_safe_xml(edu.degree)}</b>", st["job_title"]))
            meta_parts = [_safe_xml(edu.institution)]
            if edu.location:
                meta_parts.append(_safe_xml(edu.location))
            meta_parts.append(_safe_xml(edu.graduation_date))
            block.append(Paragraph("  \u2022  ".join(meta_parts), st["meta"]))
            if edu.details:
                for d in edu.details:
                    block.append(_bullet_para(d, st))
            block.append(Spacer(1, 4))
            elements.append(KeepTogether(block))

    # ── Skills ──────────────────────────────────────────────────────────────────
    if resume.skills:
        elements.append(Paragraph("SKILLS", st["section_heading"]))
        _rule(elements)
        # Group skills in rows of ~5 for readability
        row_size = 5
        rows = [resume.skills[i:i + row_size] for i in range(0, len(resume.skills), row_size)]
        for row in rows:
            elements.append(
                Paragraph("  \u2022  ".join(_safe_xml(s) for s in row), st["skills_body"])
            )

    # ── Certifications ──────────────────────────────────────────────────────────
    if resume.certifications:
        elements.append(Paragraph("CERTIFICATIONS", st["section_heading"]))
        _rule(elements)
        for cert in resume.certifications:
            parts = [f"<b>{_safe_xml(cert.name)}</b>"]
            if cert.issuer:
                parts.append(_safe_xml(cert.issuer))
            if cert.date:
                parts.append(_safe_xml(cert.date))
            elements.append(Paragraph("  \u2022  ".join(parts), st["skills_body"]))

    doc.build(elements)
    return buffer.getvalue()
