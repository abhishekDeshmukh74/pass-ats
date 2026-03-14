from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.models import ParsedResumeResponse
from backend.services.parser import parse_pdf

router = APIRouter()


@router.post("/parse-resume", response_model=ParsedResumeResponse)
async def parse_resume(file: UploadFile = File(...)):
    content_type = file.content_type or ""
    # Also allow detection by filename extension as fallback
    if content_type != "application/pdf":
        filename = file.filename or ""
        if filename.lower().endswith(".pdf"):
            content_type = "application/pdf"
        else:
            raise HTTPException(
                status_code=415,
                detail="Unsupported file type. Please upload a PDF file.",
            )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")

    try:
        text, html, file_b64, file_type = parse_pdf(file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the file.")

    return ParsedResumeResponse(text=text, html=html, file_b64=file_b64, file_type=file_type)
