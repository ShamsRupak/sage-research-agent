"""
SAGE Output Parser — extracts structured data from LLM responses.

Handles the messy reality of LLM outputs: inconsistent formatting,
extra text around JSON, missing fields, malformed tool calls.
Every parse function fails gracefully with a usable default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ParsedAction:
    """A parsed action from the ReAct loop."""
    thought: str
    action: str          # Tool name or "finish"
    action_input: dict[str, Any]


def parse_react_response(raw: str) -> ParsedAction | None:
    """
    Parse a ReAct-format response into thought, action, and action input.

    Expected format:
        Thought: <reasoning>
        Action: <tool_name>
        Action Input: <JSON>

    Returns None if parsing fails completely.
    """
    thought = ""
    action = ""
    action_input_str = ""

    # Extract Thought
    thought_match = re.search(
        r'Thought:\s*(.+?)(?=\nAction:|\Z)', raw, re.DOTALL
    )
    if thought_match:
        thought = thought_match.group(1).strip()

    # Extract Action
    action_match = re.search(
        r'Action:\s*(.+?)(?=\nAction Input:|\Z)', raw, re.DOTALL
    )
    if action_match:
        action = action_match.group(1).strip()

    # Extract Action Input
    input_match = re.search(
        r'Action Input:\s*(.+)', raw, re.DOTALL
    )
    if input_match:
        action_input_str = input_match.group(1).strip()

    if not action:
        # Try to salvage: maybe the LLM just gave a direct answer
        return ParsedAction(
            thought=raw.strip(),
            action="finish",
            action_input={"answer": raw.strip()},
        )

    # Parse action input as JSON
    action_input = _parse_json_lenient(action_input_str)
    if action_input is None:
        # If it's not JSON, treat as a simple string argument
        action_input = {"query": action_input_str}

    return ParsedAction(
        thought=thought,
        action=action.lower().strip(),
        action_input=action_input,
    )


def parse_json_response(raw: str) -> dict | None:
    """
    Extract and parse a JSON object from an LLM response.
    Handles markdown fences, extra text, trailing commas.
    Returns None on failure.
    """
    return _parse_json_lenient(raw)


def parse_critic_response(raw: str) -> dict:
    """
    Parse the Evidence Critic's JSON response.
    Returns a validated dict with all required fields,
    using defaults for any missing values.
    """
    parsed = _parse_json_lenient(raw)

    defaults = {
        "confidence": 0.0,
        "contradictions": [],
        "signal": "RETRY",
        "rationale": "Failed to parse critic response",
    }

    if parsed is None:
        return defaults

    # Validate and coerce fields
    result = {}
    result["confidence"] = _clamp(
        _to_float(parsed.get("confidence", 0.0)), 0.0, 1.0
    )
    result["contradictions"] = _to_string_list(
        parsed.get("contradictions", [])
    )

    signal = str(parsed.get("signal", "RETRY")).upper().strip()
    if signal not in ("ACCEPT", "RETRY", "ESCALATE"):
        signal = "RETRY"
    result["signal"] = signal

    result["rationale"] = str(parsed.get("rationale", "No rationale provided"))

    return result


def parse_claims_response(raw: str) -> list[dict]:
    """
    Parse the claim extraction response.
    Returns a list of {"claim": str, "confidence": float} dicts.
    """
    parsed = _parse_json_lenient(raw)
    if parsed is None or "claims" not in parsed:
        return []

    claims = []
    for item in parsed["claims"]:
        if isinstance(item, dict) and "claim" in item:
            claims.append({
                "claim": str(item["claim"]),
                "confidence": _clamp(_to_float(item.get("confidence", 0.5)), 0.0, 1.0),
            })
    return claims


def parse_cross_reference_response(raw: str) -> dict:
    """
    Parse the cross-reference response.
    Returns {"consistent": bool, "contradictions": list}.
    """
    parsed = _parse_json_lenient(raw)
    if parsed is None:
        return {"consistent": True, "contradictions": []}

    return {
        "consistent": bool(parsed.get("consistent", True)),
        "contradictions": parsed.get("contradictions", []),
    }


# ─── Internal Helpers ─────────────────────────────────────────

def _parse_json_lenient(raw: str) -> dict | None:
    """
    Attempt to parse JSON from a string that may contain
    markdown fences, surrounding text, or trailing commas.
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip()

    # Strip markdown code fences
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    cleaned = cleaned.strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find a JSON object in the text
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if json_match:
        candidate = json_match.group(0)
        # Remove trailing commas
        candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Try to find a JSON array
    array_match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if array_match:
        candidate = array_match.group(0)
        candidate = re.sub(r',\s*\]', ']', candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def _to_float(value: Any) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a float between min and max."""
    return max(min_val, min(max_val, value))


def _to_string_list(value: Any) -> list[str]:
    """Convert a value to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []