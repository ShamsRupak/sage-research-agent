"""
SAGE Claim Extractor — extracts structured factual claims from text.

Uses an LLM call with a fixed JSON schema to pull out discrete,
verifiable claims from a block of text. Each claim gets a confidence
score indicating how clearly it was stated in the source.
"""

from __future__ import annotations

from sage.llm.prompts import EXTRACT_CLAIMS_SYSTEM, EXTRACT_CLAIMS_USER
from sage.llm.parser import parse_claims_response


async def extract_claims(
    text: str,
    llm_client=None,
    max_text_length: int = 3000,
) -> dict:
    """
    Extract factual claims from a text block.

    Args:
        text: The text to extract claims from
        llm_client: An LLMClient instance (required)
        max_text_length: Max chars of input text to process

    Returns:
        Standard result dict with claims in content and structured data in metadata.
    """
    if llm_client is None:
        return {
            "success": False,
            "content": "LLM client required for claim extraction",
            "metadata": {},
        }

    # Truncate input if needed
    if len(text) > max_text_length:
        text = text[:max_text_length] + "\n[... truncated]"

    try:
        prompt = EXTRACT_CLAIMS_USER.format(text=text)
        raw_response = await llm_client.complete(
            prompt=prompt,
            system=EXTRACT_CLAIMS_SYSTEM,
            temperature=0.2,
        )

        claims = parse_claims_response(raw_response)

        if not claims:
            return {
                "success": True,
                "content": "No claims could be extracted from the text.",
                "metadata": {"num_claims": 0, "claims": []},
            }

        # Format claims as readable text
        formatted = []
        for i, c in enumerate(claims, 1):
            formatted.append(
                f"[Claim {i}] (confidence: {c['confidence']:.2f}) {c['claim']}"
            )

        return {
            "success": True,
            "content": "\n".join(formatted),
            "metadata": {
                "num_claims": len(claims),
                "claims": claims,
            },
        }

    except Exception as e:
        return {
            "success": False,
            "content": f"Claim extraction failed: {str(e)}",
            "metadata": {"error": str(e)},
        }