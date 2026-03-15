from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.models import ParsedResumeResponse
from backend.services.parser import parse_pdf
from backend.services.latex_parser import parse_tex

router = APIRouter()


@router.post("/parse-resume", response_model=ParsedResumeResponse)
async def parse_resume(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    content_type = file.content_type or ""

    if filename.endswith(".tex") or content_type in (
        "application/x-tex",
        "text/x-tex",
        "application/x-latex",
        "text/plain",
    ) and filename.endswith(".tex"):
        is_tex = True
    elif content_type == "application/pdf" or filename.endswith(".pdf"):
        is_tex = False
    else:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a PDF or LaTeX (.tex) file.",
        )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")

    try:
        if is_tex:
            text, html, file_b64, file_type = parse_tex(file_bytes)
        else:
            text, html, file_b64, file_type = parse_pdf(file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the file.")

    return ParsedResumeResponse(text=text, html=html, file_b64=file_b64, file_type=file_type)
