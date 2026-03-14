import base64

from fastapi import APIRouter, HTTPException
from backend.models import GenerateRequest, GenerateResponse
from backend.services.agents import generate_resume
from backend.services.rewriter import rewrite_pdf

router = APIRouter()


@router.post("/generate-resume", response_model=GenerateResponse)
async def generate_resume_endpoint(body: GenerateRequest):
    if not body.resume_text.strip():
        raise HTTPException(status_code=400, detail="resume_text cannot be empty.")
    if not body.jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text cannot be empty.")

    try:
        resume_data = generate_resume(body.resume_text, body.jd_text)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"AI generation failed: {exc}"
        ) from exc

    # Rewrite the original PDF with the AI-tailored text
    try:
        file_bytes = base64.b64decode(body.resume_file_b64)
        rewritten_bytes = rewrite_pdf(file_bytes, resume_data)
        rewritten_b64 = base64.b64encode(rewritten_bytes).decode()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"PDF rewrite failed: {exc}"
        ) from exc

    return GenerateResponse(resume=resume_data, rewritten_file_b64=rewritten_b64)
