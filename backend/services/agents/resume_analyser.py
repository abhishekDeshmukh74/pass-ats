"""Agent 2 — Analyse resume structure and identify gaps vs JD keywords."""

from __future__ import annotations

import logging

from backend.services.agents.llm import get_llm, parse_llm_json
from backend.services.agents.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM = """You are a resume analysis specialist.

Given a resume and a set of target JD keywords, you will:
1. Identify the resume's sections (summary, skills, each experience entry, education).
2. Map which keywords are ALREADY present in each section.
3. Identify which keywords are MISSING and suggest WHERE to place them.

Return ONLY valid JSON:
{
  "sections": {
    "summary": "the exact summary text from the resume",
    "skills": "the exact skills text from the resume",
    "experience": [
      {
        "company": "company name",
        "title": "job title",
        "text": "the exact bullet points text for this role"
      }
    ],
    "education": "the exact education text"
  },
  "present_keywords": ["keyword1", "keyword2"],
  "missing_keywords": ["keyword3", "keyword4"],
  "gap_analysis": "Brief analysis of what needs to change. Which keywords fit naturally into which sections. Be specific about placement."
}

RULES:
- The "text" fields must be EXACT verbatim copies from the resume.
- Be specific about which missing keywords should go into which section/bullet.
- Do NOT suggest adding keywords that don't make sense for the candidate's actual experience.
- Prioritise high-impact keywords (job title match, core technical skills, key methodologies)."""


def analyse_resume(state: AgentState) -> dict:
    """Node: analyse resume sections and identify keyword gaps."""
    llm = get_llm()

    keywords_str = ", ".join(state.get("jd_keywords", []))

    resp = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"## Original Resume\n\n{state['resume_text']}\n\n"
            f"## Target Keywords\n\n{keywords_str}"
        )},
    ])

    data = parse_llm_json(resp.content)
    sections = data.get("sections", {})
    gap = data.get("gap_analysis", "")
    missing = data.get("missing_keywords", [])

    logger.info("Resume analyser: %d present, %d missing keywords. Sections: %s",
                len(data.get("present_keywords", [])), len(missing),
                list(sections.keys()))

    return {
        "resume_sections": sections,
        "gap_analysis": gap,
    }
