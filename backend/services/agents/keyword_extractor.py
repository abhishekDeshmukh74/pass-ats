"""Agent 1 — Extract and categorise keywords from the job description."""

from __future__ import annotations

import logging

from backend.services.agents.llm import get_llm, parse_llm_json
from backend.services.agents.state import AgentState

logger = logging.getLogger(__name__)

_SYSTEM = """You are a keyword extraction specialist for ATS (Applicant Tracking System) optimisation.

Given a job description, extract ALL important keywords and categorise them.

Return ONLY valid JSON:
{
  "keywords": ["keyword1", "keyword2", ...],
  "categories": {
    "technical_skills": ["Python", "React", ...],
    "soft_skills": ["leadership", "collaboration", ...],
    "tools_platforms": ["AWS", "Docker", ...],
    "domain_knowledge": ["microservices", "CI/CD", ...],
    "certifications": ["AWS Certified", ...],
    "action_verbs": ["architected", "optimised", ...]
  }
}

RULES:
- Extract 30-60 unique keywords/phrases.
- Include specific technologies, frameworks, methodologies mentioned.
- Include implied skills (e.g. if "full stack" is mentioned, include both frontend and backend terms).
- Normalise casing (e.g. "javascript" → "JavaScript").
- Do NOT duplicate keywords across categories.
- Include important action verbs from the JD."""


def extract_keywords(state: AgentState) -> dict:
    """Node: extract JD keywords and categories."""
    llm = get_llm()

    resp = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"## Job Description\n\n{state['jd_text']}"},
    ])

    data = parse_llm_json(resp.content)
    keywords = list(set(data.get("keywords", [])))
    categories = data.get("categories", {})

    logger.info("Keyword extractor: %d unique keywords in %d categories.",
                len(keywords), len(categories))

    return {
        "jd_keywords": keywords,
        "keyword_categories": categories,
    }
