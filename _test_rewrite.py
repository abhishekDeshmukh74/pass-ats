"""Quick integration test for the pypdf-based parser and rewriter."""
import io
from reportlab.pdfgen import canvas

from backend.services.parser import parse_pdf
from backend.services.rewriter import rewrite_pdf
from backend.models import ResumeData, TextReplacement


def make_test_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, 720, "Senior Software Engineer")
    c.setFont("Helvetica", 11)
    c.drawString(72, 700, "Built scalable microservices using Python and Flask framework")
    c.drawString(72, 680, "Managed team of 5 developers for cloud infrastructure projects")
    c.save()
    return buf.getvalue()


def main():
    test_pdf = make_test_pdf()
    print(f"Created test PDF: {len(test_pdf)} bytes")

    text, html, b64, ftype = parse_pdf(test_pdf)
    print("\n=== ORIGINAL TEXT ===")
    print(text.strip())

    resume = ResumeData(
        name="Test",
        replacements=[
            TextReplacement(
                old="Built scalable microservices using Python and Flask framework",
                new="Architected distributed microservices leveraging Python, FastAPI, and Kubernetes",
            ),
            TextReplacement(
                old="Managed team of 5 developers for cloud infrastructure projects",
                new="Led cross-functional team of 5 engineers delivering AWS cloud-native solutions",
            ),
        ],
    )

    result = rewrite_pdf(test_pdf, resume)
    print(f"\nRewritten PDF: {len(result)} bytes")

    text2, _, _, _ = parse_pdf(result)
    print("\n=== REWRITTEN TEXT ===")
    print(text2.strip())

    ok1 = "Architected distributed" in text2
    ok2 = "Led cross-functional" in text2
    ok3 = "Senior Software Engineer" in text2

    print(f"\nReplacement 1: {'OK' if ok1 else 'FAIL'}")
    print(f"Replacement 2: {'OK' if ok2 else 'FAIL'}")
    print(f"Header preserved: {'OK' if ok3 else 'FAIL'}")

    if ok1 and ok2 and ok3:
        print("\nAll checks passed!")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
