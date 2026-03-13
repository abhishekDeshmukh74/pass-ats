import json
import os
from groq import Groq
from backend.models import ResumeData

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is not set.")
        _client = Groq(api_key=api_key)
    return _client


_SYSTEM_PROMPT = """You are an expert ATS (Applicant Tracking System) resume writer.
Your task is to tailor a candidate's resume TEXT CONTENT to pass ATS screening for a specific job description.

STRICT RULES — structure preservation:
- You MUST keep the EXACT SAME number of experience entries, job titles, company names, and dates as the original.
- You MUST keep the EXACT SAME number of education entries, degrees, institutions, and graduation dates.
- You MUST keep the EXACT SAME certifications (names, issuers, dates).
- Do NOT add, remove, or merge any job, education, or certification entry.
- Do NOT invent responsibilities, skills, or credentials that are not implied by the original.

What you MAY change (text content only):
- Rewrite bullet point text to use JD keywords and phrasing naturally — keep the same number of bullets per role.
- Rewrite the professional summary to target this specific role.
- Reorder and augment the skills list to surface the most JD-relevant ones first; you may add widely-used aliases (e.g. "JS" → "JavaScript") but not fabricate skills.

ATS scoring:
- After tailoring, score the resume's keyword match against the JD from 0 to 100 (integer).
  - 90-100: near-perfect keyword coverage
  - 70-89: strong match
  - 50-69: moderate match
  - below 50: weak match
- List the top JD keywords/phrases that now appear in the resume as "matched_keywords" (max 15 items).

Return ONLY a valid JSON object — no markdown fences, no prose. Schema:
{
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "linkedin": "string or null",
  "github": "string or null",
  "location": "string or null",
  "summary": "string",
  "skills": ["string"],
  "experience": [
    {
      "job_title": "string",
      "company": "string",
      "location": "string or null",
      "start_date": "string",
      "end_date": "string",
      "bullets": ["string"]
    }
  ],
  "education": [
    {
      "degree": "string",
      "institution": "string",
      "location": "string or null",
      "graduation_date": "string",
      "details": ["string"] or null
    }
  ],
  "certifications": [
    {
      "name": "string",
      "issuer": "string or null",
      "date": "string or null"
    }
  ],
  "ats_score": 0,
  "matched_keywords": ["string"]
}"""


def generate_resume(resume_text: str, jd_text: str) -> ResumeData:
    """Call Groq to generate a tailored resume and return a validated ResumeData."""
    client = _get_client()

    user_prompt = (
        f"## Original Resume\n\n{resume_text}\n\n"
        f"## Job Description\n\n{jd_text}\n\n"
        "Tailor the resume text content to match this job description.\n"
        "IMPORTANT: Preserve every job entry, company, date, degree, and certification exactly. "
        "Only rewrite bullet text, summary, and skills. "
        "Also provide ats_score (0-100) and matched_keywords. Return only the JSON object."
    )

    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    raw = completion.choices[0].message.content
    data = json.loads(raw)
    return ResumeData(**data)
