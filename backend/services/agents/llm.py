"""Shared LLM instance and helpers for all agents."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
# Matches a complete {"old": "...", "new": "..."} replacement object
_REPL_OBJ_RE = re.compile(
    r'\{"old"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"new"\s*:\s*"(?:[^"\\]|\\.)*"\s*\}',
    re.DOTALL,
)


def _repair_json(text: str) -> dict:
    """Best-effort repair of malformed/truncated LLM JSON output."""
    # Pass 1: strip trailing commas before ] or }
    repaired = re.sub(r",\s*([\]}])", r"\1", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Pass 2: truncated JSON — close any unclosed brackets/braces.
    # Scan backwards to find the last position that, when closed, is valid.
    for end in range(len(repaired), max(len(repaired) - 200, 0), -1):
        chunk = repaired[:end]
        opens = chunk.count("{") - chunk.count("}")
        opens_sq = chunk.count("[") - chunk.count("]")
        if opens < 0 or opens_sq < 0:
            continue
        candidate = chunk.rstrip(",\n\r\t ") + ("]" * opens_sq) + ("}" * opens)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # Pass 3: regex extraction — pull every complete replacement object out of
    # whatever the LLM produced, even if the outer structure is broken.
    objects = _REPL_OBJ_RE.findall(text)
    if objects:
        replacements = [json.loads(o) for o in objects]
        return {"replacements": replacements, "fixes_applied": ["(recovered via regex)"]}

    raise json.JSONDecodeError(
        f"Could not parse or repair LLM JSON output", text, 0
    )


def parse_llm_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown fences if present."""
    text = text.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _repair_json(text)


@lru_cache(maxsize=1)
def get_llm():
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()

    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
        return ChatGoogleGenerativeAI(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            google_api_key=api_key,
            temperature=0.2,
            max_output_tokens=8192,
        )

    # Default: groq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set.")
    return ChatGroq(
        model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        api_key=api_key,
        temperature=0.2,
        max_tokens=8192,
    )
