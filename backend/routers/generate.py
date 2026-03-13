from fastapi import APIRouter, HTTPException
from backend.models import GenerateRequest, ResumeData
from backend.services.groq_service import generate_resume

router = APIRouter()


@router.post("/generate-resume", response_model=ResumeData)
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

    return resume_data
