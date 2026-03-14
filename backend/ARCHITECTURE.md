# Backend Architecture

## Overview

FastAPI backend for the pass-ats resume tailor. Receives a PDF resume and job description, runs a **LangGraph multi-agent pipeline** (6 sequential AI agents) to rewrite resume content for ATS optimisation, and returns a modified PDF preserving the original layout.

## Directory Structure

```
backend/
├── main.py              # FastAPI app, CORS, router registration, logging setup
├── models.py            # Pydantic models (request/response schemas)
├── routers/
│   ├── resume.py        # POST /api/parse-resume — PDF upload + text extraction
│   ├── jd.py            # POST /api/scrape-jd — URL → JD text scraper
│   ├── generate.py      # POST /api/generate-resume — AI rewrite + PDF output
│   └── pipeline.py      # GET  /api/pipeline-runs — run list + detail inspection
└── services/
    ├── parser.py         # PDF text extraction (PyMuPDF get_text)
    ├── scraper.py        # URL scraping for job descriptions
    ├── rewriter.py       # In-place PDF text replacement (redact + re-draw)
    ├── db.py             # MongoDB persistence for pipeline run tracking
    └── agents/           # LangGraph multi-agent pipeline
        ├── __init__.py           # Re-exports generate_resume()
        ├── state.py              # AgentState TypedDict (shared pipeline state)
        ├── llm.py                # Shared ChatGroq instance + parse_llm_json()
        ├── keyword_extractor.py  # Agent 1: Extract JD keywords
        ├── resume_analyser.py    # Agent 2: Section analysis + gap identification
        ├── scorer.py             # Agents 3 & 6: ATS scoring (before + after)
        ├── rewriter_agent.py     # Agent 4: Generate old→new replacements
        ├── qa_agent.py           # Agent 5: Validate & deduplicate keywords
        └── graph.py              # StateGraph wiring + public generate_resume()
```

## Request Flow (Generate)

```
Frontend                    Backend
   │                          │
   ├─ POST /api/generate ────►│
   │  { resume_text,          │
   │    jd_text,              │
   │    resume_file_b64 }     │
   │                          ├─ agents.generate_resume()
   │                          │   → LangGraph pipeline (6 agents):
   │                          │     1. extract_keywords  → JD keywords
   │                          │     2. analyse_resume    → gap analysis
   │                          │     3. score_before      → baseline ATS score
   │                          │     4. rewrite_sections  → raw replacements
   │                          │     5. qa_deduplicate    → validated replacements
   │                          │     6. score_extract     → final ATS score + structured data
   │                          │   → ResumeData (with replacements[])
   │                          │
   │                          ├─ rewriter.rewrite_pdf(original_bytes, resume_data)
   │                          │   → For each {old, new} replacement:
   │                          │     1. Find spans matching "old" text
   │                          │     2. Redact those spans
   │                          │     3. Insert "new" text at same position
   │                          │   → Returns modified PDF bytes
   │                          │
   │◄─ { resume, b64_pdf } ──┤
```

## LangGraph Pipeline

The AI logic is split into 6 sequential agents using LangGraph's `StateGraph`:

| # | Agent | Node Name | Purpose |
|---|-------|-----------|---------|
| 1 | Keyword Extractor | `extract_keywords` | Extract 30–60 JD keywords, categorised |
| 2 | Resume Analyser | `analyse_resume` | Map resume sections, find keyword gaps |
| 3 | Pre-Rewrite Scorer | `score_before` | Baseline ATS score before any rewriting |
| 4 | Rewriter | `rewrite_sections` | Generate old→new replacements (max 2 per keyword) |
| 5 | QA Agent | `qa_deduplicate` | Validate old text accuracy, deduplicate keywords |
| 6 | Final Scorer | `score_extract` | Score final resume, extract structured data |

All agents share an `AgentState` TypedDict. See `backend/services/agents/AGENTS.md` for details.

## Pipeline Run Tracking

Every pipeline execution is tracked in MongoDB (best-effort — failures never break the pipeline):

1. **`graph.py`** creates a pipeline run in MongoDB at the start via `db.create_pipeline_run()`
2. Each agent is wrapped by `_tracked()`, which records:
   - Agent name, execution duration (ms)
   - Input state summary (relevant keys only, via `_AGENT_INPUT_KEYS` mapping)
   - Output data (serialised, truncated for storage)
3. On completion: `db.complete_pipeline_run()` saves ATS scores, replacement count, and name
4. On failure: `db.fail_pipeline_run()` saves the error message
5. Run ID is stored in a `contextvars.ContextVar` for thread-safe tracking

**Inspection endpoints**:
- `GET /api/pipeline-runs` — list runs with summary (status, timestamps, agent names)
- `GET /api/pipeline-runs/{id}` — full detail with per-agent timing, I/O data

## Key Data Models (models.py)

- **`TextReplacement`**: `{old: str, new: str}` — a single find-and-replace pair
- **`ResumeData`**: Full structured resume + `replacements: list[TextReplacement]` + `ats_score` + `ats_score_before`
- **`GenerateRequest`**: `{resume_text, jd_text, resume_file_b64, resume_file_type}`
- **`GenerateResponse`**: `{resume: ResumeData, rewritten_file_b64: str}`

## Critical Path: Text Matching

The most fragile part of the pipeline is matching AI-generated `old` strings against PDF spans:

1. **`parser.py`** extracts text using `page.get_text("text")` — this inserts newlines between lines and spaces between words.
2. **`agents/rewriter_agent.py`** (Agent 4) returns `old` strings that should be verbatim substrings.
3. **`agents/qa_agent.py`** (Agent 5) validates that each `old` string exists in the original resume text.
4. **`rewriter.py`** must find these `old` strings in the PDF's span-level text representation (from `page.get_text("dict")`).

The span-level text and `get_text("text")` output differ in whitespace, ligatures, and special characters. The rewriter uses:
- **Unicode NFKC normalisation** to handle ligatures (ﬁ → fi)
- **Character mapping** for smart quotes, dashes, bullets
- **Space injection** between consecutive spans
- **Fallback `page.search_for()`** when span matching fails

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for AI calls |
| `ALLOWED_ORIGINS` | Yes | Comma-separated CORS origins |
| `MONGODB_URL` | No | MongoDB connection string for pipeline run tracking |

## Running

```bash
uvicorn backend.main:app --reload --port 8000
```
