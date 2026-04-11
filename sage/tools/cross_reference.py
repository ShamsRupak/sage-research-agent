"""
SAGE Cross-Reference Tool — checks internal consistency of claims.

Takes a list of claims and uses an LLM call to identify contradictions
or inconsistencies between them. This feeds into the Evidence Critic's
assessment of evidence quality.
"""

from __future__ import annotations

from sage.llm.prompts import CROSS_REFERENCE_SYSTEM, CROSS_REFERENCE_USER
from sage.llm.parser import parse_cross_reference_response


async def cross_reference(
    claims: list[str] | str,
    llm_client=None,
) -> dict:
    """
    Check a list of claims for internal consistency.

    Args:
        claims: List of claim strings, or a single string with claims
        llm_client: An LLMClient instance (required)

    Returns:
        Standard result dict with consistency analysis.
    """
    if llm_client is None:
        return {
            "success": False,
            "content": "LLM client required for cross-referencing",
            "metadata": {},
        }

    # Normalize input
    if isinstance(claims, str):
        claims_text = claims
    elif isinstance(claims, list):
        claims_text = "\n".join(f"- {c}" for c in claims)
    else:
        return {
            "success": False,
            "content": "Claims must be a list of strings or a single string",
            "metadata": {},
        }

    if not claims_text.strip():
        return {
            "success": True,
            "content": "No claims provided to cross-reference.",
            "metadata": {"consistent": True, "contradictions": []},
        }

    try:
        prompt = CROSS_REFERENCE_USER.format(claims=claims_text)
        raw_response = await llm_client.complete(
            prompt=prompt,
            system=CROSS_REFERENCE_SYSTEM,
            temperature=0.2,
        )

        result = parse_cross_reference_response(raw_response)

        if result["consistent"]:
            content = "All claims are internally consistent."
        else:
            contradiction_lines = []
            for c in result["contradictions"]:
                if isinstance(c, dict):
                    contradiction_lines.append(
                        f"CONFLICT: '{c.get('claim_a', '?')}' vs "
                        f"'{c.get('claim_b', '?')}' — {c.get('explanation', '')}"
                    )
            content = "Contradictions found:\n" + "\n".join(contradiction_lines)

        return {
            "success": True,
            "content": content,
            "metadata": result,
        }

    except Exception as e:
        return {
            "success": False,
            "content": f"Cross-reference failed: {str(e)}",
            "metadata": {"error": str(e)},
        }