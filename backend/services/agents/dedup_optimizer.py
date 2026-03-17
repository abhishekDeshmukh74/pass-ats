"""Deduplication Optimizer — removes excessive repetition across the resume.

Scans the full ``draft_resume`` for action verbs and phrases that appear
more than 3 times and replaces duplicates with contextually appropriate
synonyms, keeping the resume varied and human-sounding.

Problem this solves:
    The three optimizers (summary, skills, experience) run independently.
    Each may inject the same high-value action verbs (e.g. "Developed",
    "Deployed", "Implemented") or keyword phrases, resulting in 5–6
    occurrences across the resume.  ATS systems accept this, but human
    recruiters find it repetitive and generic.

Approach:
    1. **Deterministic scan** — ``_find_duplicates()`` tokenises all bullets
       and sections, counts verb/phrase frequency, and flags anything
       appearing > ``MAX_OCCURRENCES`` (3) times.
    2. **LLM rewrite** — sends the flagged duplicates plus the full draft
       to the LLM, which returns targeted replacements using varied synonyms
       while preserving meaning and ATS keywords.

Graph position:
    ``merge_resume`` → **dedup_optimizer** → ``truth_guard``

State reads:
    ``draft_resume``

State writes:
    ``draft_resume`` — updated in place with synonym replacements.

Downstream consumers:
    ``truth_guard`` → ``critic`` → ``final_score`` → ``export``
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections import Counter

from backend.services.agents.llm import invoke_llm_json
from backend.services.agents.state import ResumeGraphState

logger = logging.getLogger(__name__)

MAX_OCCURRENCES = 3

# Common action verbs that optimizers tend to overuse
_ACTION_VERBS = [
    "achieved", "architected", "automated", "built", "configured",
    "coordinated", "created", "delivered", "deployed", "designed",
    "developed", "enabled", "engineered", "established", "executed",
    "extended", "implemented", "improved", "increased", "integrated",
    "launched", "led", "maintained", "managed", "migrated", "modernized",
    "optimized", "orchestrated", "reduced", "refactored", "resolved",
    "scaled", "spearheaded", "streamlined", "transformed", "wrote",
]


def _collect_text_blocks(draft: dict) -> list[dict]:
    """Extract all text blocks from the draft resume with their locations.

    Returns a list of ``{"text": str, "section": str, "index": int}`` dicts
    so the LLM knows where each block lives for targeted replacement.
    """
    blocks: list[dict] = []

    summary = draft.get("summary", "")
    if summary:
        blocks.append({"text": summary, "section": "summary", "index": 0})

    for i, exp in enumerate(draft.get("experience", [])):
        for j, bullet in enumerate(exp.get("bullets", [])):
            blocks.append({
                "text": bullet,
                "section": f"experience[{i}].bullets[{j}]",
                "index": len(blocks),
            })

    for i, proj in enumerate(draft.get("projects", [])):
        for j, bullet in enumerate(proj.get("bullets", [])):
            blocks.append({
                "text": bullet,
                "section": f"projects[{i}].bullets[{j}]",
                "index": len(blocks),
            })

    return blocks


def _find_duplicates(blocks: list[dict]) -> dict[str, int]:
    """Count action verbs/phrases across all text blocks + flag those > MAX.

    Returns:
        ``{verb: count}`` for verbs exceeding ``MAX_OCCURRENCES``.
    """
    all_text = " ".join(b["text"] for b in blocks).lower()
    words = re.findall(r"\b[a-z]+\b", all_text)
    word_counts = Counter(words)

    duplicates: dict[str, int] = {}
    for verb in _ACTION_VERBS:
        count = word_counts.get(verb, 0)
        if count > MAX_OCCURRENCES:
            duplicates[verb] = count

    return duplicates


_SYSTEM = """You are a resume deduplication specialist.

You receive a draft resume and a list of overused words/phrases with their
counts. Your job is to replace EXCESS occurrences with varied synonyms so
that no word appears more than {max_occ} times total across the resume.

═══ HARD RULES ═══

1. Keep the FIRST {max_occ} occurrences of each flagged word unchanged.
   Only replace the extras (occurrence {next_occ}+).
2. Replacements must be contextually appropriate synonyms — not random words.
3. NEVER change the meaning, facts, metrics, or technical terms.
4. NEVER remove or add information — only swap the overused verb/phrase.
5. Keep the replacement the same tense and grammatical form as the original.
6. Return ONLY the sections/bullets you actually changed.

═══ OUTPUT FORMAT (pure JSON, no markdown) ═══

{{
  "changes": [
    {{
      "section": "experience[0].bullets[2]",
      "original_text": "exact original bullet text",
      "updated_text": "bullet with synonym replacement",
      "word_replaced": "developed",
      "replacement": "engineered"
    }}
  ]
}}

If no changes are needed, return: {{"changes": []}}"""


def dedup_optimizer_node(state: ResumeGraphState) -> dict:
    """LangGraph node: deduplicate overused verbs/phrases across the resume.

    Workflow:
        1. Collect all text blocks (summary, experience bullets, project
           bullets) from ``draft_resume``.
        2. Count action verb frequency via ``_find_duplicates()``.
        3. If no verb exceeds ``MAX_OCCURRENCES`` (3), return immediately
           (no LLM call needed).
        4. Otherwise, send the draft + duplicate list to the LLM for
           targeted synonym replacement.
        5. Apply the LLM's changes back into ``draft_resume``.

    Args:
        state: Pipeline state; reads ``draft_resume``.

    Returns:
        ``{"draft_resume": dict}`` — updated with synonym replacements,
        or the original if no dedup was needed.
    """
    draft = copy.deepcopy(state.get("draft_resume", {}))
    blocks = _collect_text_blocks(draft)

    if not blocks:
        logger.info("Dedup: no text blocks found, skipping.")
        return {"draft_resume": draft}

    duplicates = _find_duplicates(blocks)

    if not duplicates:
        logger.info("Dedup: no overused verbs detected, skipping.")
        return {"draft_resume": draft}

    logger.info(
        "Dedup: found %d overused verb(s): %s",
        len(duplicates),
        ", ".join(f"{v}({c}x)" for v, c in duplicates.items()),
    )

    system_prompt = _SYSTEM.format(
        max_occ=MAX_OCCURRENCES,
        next_occ=MAX_OCCURRENCES + 1,
    )

    user_msg = json.dumps({
        "overused_words": duplicates,
        "max_allowed": MAX_OCCURRENCES,
        "resume_blocks": blocks,
    }, indent=2)

    result = invoke_llm_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ])

    changes = result.get("changes", [])
    if not changes:
        logger.info("Dedup: LLM returned no changes.")
        return {"draft_resume": draft}

    # Apply changes back into the draft
    applied = 0
    for change in changes:
        section = change.get("section", "")
        updated_text = change.get("updated_text", "")
        if not section or not updated_text:
            continue

        if section == "summary":
            draft["summary"] = updated_text
            applied += 1
        elif section.startswith("experience["):
            match = re.match(r"experience\[(\d+)\]\.bullets\[(\d+)\]", section)
            if match:
                exp_idx, bul_idx = int(match.group(1)), int(match.group(2))
                try:
                    draft["experience"][exp_idx]["bullets"][bul_idx] = updated_text
                    applied += 1
                except (IndexError, KeyError):
                    logger.warning("Dedup: invalid index %s, skipping.", section)
        elif section.startswith("projects["):
            match = re.match(r"projects\[(\d+)\]\.bullets\[(\d+)\]", section)
            if match:
                proj_idx, bul_idx = int(match.group(1)), int(match.group(2))
                try:
                    draft["projects"][proj_idx]["bullets"][bul_idx] = updated_text
                    applied += 1
                except (IndexError, KeyError):
                    logger.warning("Dedup: invalid index %s, skipping.", section)

    logger.info("Dedup: applied %d/%d synonym replacements.", applied, len(changes))
    return {"draft_resume": draft}
