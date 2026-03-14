"""Agent 5 — Score the rewritten resume and extract structured data."""

from __future__ import annotations

import logging

from backend.services.agents.llm import get_llm, parse_llm_json
from backend.services.agents.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM = """You are an ATS scoring and resume parsing specialist.

You receive the original resume text and the final set of replacements.
Apply the replacements mentally to produce the "final resume".

Then:
1. Score the final resume against the JD keywords (0-100).
2. List all matched keywords.
3. Extract structured resume data for the API response.

Return ONLY valid JSON:
{
  "ats_score": 92,
  "matched_keywords": ["keyword1", "keyword2"],
  "name": "string",
  "email": "string or null",
  "phone": "string or null",
  "linkedin": "string or null",
  "github": "string or null",
  "location": "string or null",
  "summary": "the rewritten summary",
  "skills": ["skill1", "skill2"],
  "experience": [
    {
      "job_title": "string",
      "company": "string",
      "location": "string or null",
      "start_date": "string",
      "end_date": "string",
      "bullets": ["rewritten bullet 1", "rewritten bullet 2"]
    }
  ],
  "education": [
    {
      "degree": "string",
      "institution": "string",
      "location": "string or null",
      "graduation_date": "string",
      "details": null
    }
  ],
  "certifications": []
}

SCORING RULES:
- Count what percentage of JD keywords appear in the final resume.
- Weight technical skills and job-title keywords more heavily.
- Do NOT inflate the score — be accurate."""


_SCORE_BEFORE_SYSTEM = """You are an ATS scoring specialist.

You receive the ORIGINAL resume text (before any rewriting) and a list of JD keywords.
Score how well the current resume matches the JD keywords on a scale of 0-100.

Return ONLY valid JSON:
{
  "ats_score_before": 55
}

SCORING RULES:
- Count what percentage of JD keywords appear in the original resume.
- Weight technical skills and job-title keywords more heavily.
- Do NOT inflate the score — be accurate."""


def score_before_rewrite(state: AgentState) -> dict:
    """Node: score the original resume BEFORE any rewriting."""
    llm = get_llm()
    keywords = state.get("jd_keywords", [])

    resp = llm.invoke([
        {"role": "system", "content": _SCORE_BEFORE_SYSTEM},
        {"role": "user", "content": (
            f"## Original Resume\n\n{state['resume_text']}\n\n"
            f"## JD Keywords\n\n{', '.join(keywords)}\n\n"
            "Score the original resume against these keywords."
        )},
    ])

    data = parse_llm_json(resp.content)
    score = data.get("ats_score_before", 0)
    logger.info("ATS Pre-Rewrite Score: %d", score)

    return {"ats_score_before": score}


def score_and_extract(state: AgentState) -> dict:
    """Node: score the final resume and extract structured fields."""
    llm = get_llm()

    replacements = state.get("replacements", [])
    replacements_str = "\n".join(
        f"OLD: {r.old}\nNEW: {r.new}\n---"
        for r in replacements
    )

    keywords = state.get("jd_keywords", [])

    resp = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"## Original Resume\n\n{state['resume_text']}\n\n"
            f"## JD Keywords\n\n{', '.join(keywords)}\n\n"
            f"## Applied Replacements\n\n{replacements_str}\n\n"
            f"## Job Description\n\n{state['jd_text']}\n\n"
            "Score the final resume and extract structured data."
        )},
    ])

    data = parse_llm_json(resp.content)

    score = data.get("ats_score", 0)
    matched = data.get("matched_keywords", [])

    logger.info("ATS Scorer: score=%d, matched=%d keywords.", score, len(matched))

    return {
        "ats_score": score,
        "matched_keywords": matched,
        "name": data.get("name", ""),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "linkedin": data.get("linkedin"),
        "github": data.get("github"),
        "location": data.get("location"),
        "summary": data.get("summary"),
        "skills": data.get("skills", []),
        "experience": data.get("experience", []),
        "education": data.get("education", []),
        "certifications": data.get("certifications", []),
    }
