# LangGraph Multi-Agent Pipeline

## Overview

The AI logic uses **LangGraph** to orchestrate 6 sequential agents. Each agent is a standalone node that reads from and writes to a shared `AgentState` TypedDict.

All agents use `ChatGroq` (LLaMA 3.3 70B, temperature 0.2) via `llm.py`.

## Pipeline Flow

```
extract_keywords → analyse_resume → score_before → rewrite_sections → qa_deduplicate → score_extract → END
```

## Agent Details

### Agent 1 — Keyword Extractor (`keyword_extractor.py`)

**Input**: `jd_text`
**Output**: `jd_keywords`, `keyword_categories`

Extracts 30–60 unique keywords from the job description and categorises them into:
- `technical_skills`, `soft_skills`, `tools_platforms`
- `domain_knowledge`, `certifications`, `action_verbs`

### Agent 2 — Resume Analyser (`resume_analyser.py`)

**Input**: `resume_text`, `jd_keywords`
**Output**: `resume_sections`, `gap_analysis`

- Identifies resume sections (summary, skills, each experience entry, education)
- Maps which keywords are already present vs missing
- Produces a gap analysis with specific placement recommendations

### Agent 3 — Pre-Rewrite Scorer (`scorer.py`)

**Input**: `resume_text`, `jd_keywords`, `jd_text`
**Output**: `ats_score_before`

Scores the **original** resume against the JD keywords before any rewriting. This provides a baseline for the before/after ATS score comparison shown in the frontend.

### Agent 4 — Rewriter (`rewriter_agent.py`)

**Input**: `resume_text`, `keyword_categories`, `gap_analysis`
**Output**: `raw_replacements` (list of `{old, new}` dicts)

Generates old→new text replacements with strict rules:
- `old` must be **verbatim** from the original resume (character-for-character)
- `new` must be within **±20%** of the same length
- Each keyword appears at **most 2 times** across all replacements
- Keywords are spread evenly; synonyms/variations are used

### Agent 5 — QA Agent (`qa_agent.py`)

**Input**: `resume_text`, `jd_keywords`, `raw_replacements`
**Output**: `replacements` (list of `TextReplacement` Pydantic models)

Validates and fixes:
1. Checks each `old` text exists in the original resume
2. Counts keyword frequency across all `new` texts, flags overuse (>2)
3. Instructs LLM to fix duplicates with synonyms
4. Programmatic dedup safety net (removes duplicate `old` entries)

### Agent 6 — Final Scorer (`scorer.py`)

**Input**: `resume_text`, `jd_keywords`, `jd_text`, `replacements`
**Output**: `ats_score`, `matched_keywords`, `name`, `email`, `skills`, `experience`, etc.

- Applies replacements mentally to produce the "final resume"
- Scores keyword coverage (0–100)
- Extracts structured fields needed by `ResumeData`

## Pipeline Run Tracking

Every pipeline execution is tracked in MongoDB via `db.py` (best-effort):

1. A run is created at the start of `generate_resume()` with status `"running"`
2. Each agent is wrapped by `_tracked()` in `graph.py`, which records:
   - Agent name and execution duration (ms)
   - Input summary (relevant state keys only)
   - Output data (serialised, truncated for storage)
3. On success: final result saved with ATS scores, replacement count, and name
4. On failure: error message saved

The run ID is stored in a `contextvars.ContextVar` for thread-safe tracking.

## Shared State (`state.py`)

`AgentState` is a `TypedDict` with annotated reducers:
- **List fields** use `_merge_lists` (extend, not replace)
- **Scalar/dict fields** use `_overwrite` (last-write-wins)

Key state fields:

| Category | Fields |
|----------|--------|
| Inputs | `resume_text`, `jd_text` |
| Agent 1 | `jd_keywords` (list, merge), `keyword_categories` (dict, overwrite) |
| Agent 2 | `resume_sections` (dict, overwrite), `gap_analysis` (str, overwrite) |
| Agent 3 | `ats_score_before` (int, overwrite) |
| Agent 4 | `raw_replacements` (list, merge) |
| Agent 5 | `replacements` (list[TextReplacement], merge) |
| Agent 6 | `ats_score` (int), `matched_keywords` (list), structured fields |

## LLM Configuration (`llm.py`)

| Parameter | Value |
|-----------|-------|
| Model | `llama-3.3-70b-versatile` |
| Temperature | `0.2` |
| Max tokens | `8192` |
| Provider | Groq (via `langchain-groq`) |

`parse_llm_json()` safely extracts JSON from LLM responses, handling markdown code fences.

## Public API (`graph.py`)

```python
from backend.services.agents import generate_resume

resume_data: ResumeData = generate_resume(resume_text, jd_text)
```

Drop-in replacement for the previous monolithic `groq_service.generate_resume()`.
