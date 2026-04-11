"""
SAGE Query Decomposer — breaks a complex query into a DAG of sub-goals.

Uses a single LLM call to propose sub-questions, then deterministic Python
code validates, deduplicates, and structures them into the DAG with
dependency edges. The LLM suggests; the planner decides.
"""

from __future__ import annotations

import json
import re
from sage.planner.dag import DAGNode, PlanDAG


# Heuristic patterns for detecting multi-part queries
CONJUNCTION_PATTERNS = [
    r'\band\b',
    r'\bvs\.?\b',
    r'\bversus\b',
    r'\bcompare\b',
    r'\bcontrast\b',
    r'\btrade-?offs?\b',
    r'\brelationship between\b',
    r'\bhow does .+ affect\b',
    r'\bwhat are the .+ and .+\b',
]

DECOMPOSITION_PROMPT = """You are a research planning assistant. Given a complex research question, decompose it into 3-6 atomic sub-questions that together fully answer the original question.

Rules:
1. Each sub-question must be specific and independently answerable via web search
2. Sub-questions should cover different aspects of the original query
3. If sub-question B requires knowing the answer to sub-question A first, mark that dependency
4. Return ONLY valid JSON — no markdown, no explanation

Return this exact JSON format:
{{
  "sub_questions": [
    {{
      "id": "sub_1",
      "question": "The sub-question text",
      "depends_on": []
    }},
    {{
      "id": "sub_2",
      "question": "Another sub-question",
      "depends_on": ["sub_1"]
    }}
  ]
}}

Original question: {query}"""


def detect_complexity(query: str) -> int:
    """
    Heuristic estimate of query complexity based on structural patterns.
    Returns a score from 1-5 that hints at how many sub-goals to expect.
    """
    score = 1
    query_lower = query.lower()
    for pattern in CONJUNCTION_PATTERNS:
        if re.search(pattern, query_lower):
            score += 1
    # Long queries tend to be more complex
    word_count = len(query.split())
    if word_count > 20:
        score += 1
    if word_count > 40:
        score += 1
    return min(score, 5)


def parse_decomposition_response(raw_response: str) -> list[dict]:
    """
    Parse the LLM's JSON response into a list of sub-question dicts.
    Handles common LLM output issues: markdown fences, trailing commas, etc.
    Returns an empty list on parse failure.
    """
    # Strip markdown code fences if present
    cleaned = raw_response.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    cleaned = cleaned.strip()

    # Try to find JSON object in the response
    # Sometimes LLMs add text before/after the JSON
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)

    # Remove trailing commas before } or ]
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []

    if "sub_questions" not in data:
        return []

    sub_questions = data["sub_questions"]
    if not isinstance(sub_questions, list):
        return []

    # Validate each sub-question has required fields
    validated = []
    for sq in sub_questions:
        if not isinstance(sq, dict):
            continue
        if "id" not in sq or "question" not in sq:
            continue
        validated.append({
            "id": str(sq["id"]),
            "question": str(sq["question"]),
            "depends_on": [
                str(d) for d in sq.get("depends_on", [])
                if isinstance(d, str)
            ],
        })

    return validated


def validate_dependencies(sub_questions: list[dict]) -> list[dict]:
    """
    Remove dependency references to non-existent IDs.
    This prevents the DAG from breaking if the LLM hallucinates a dependency.
    """
    valid_ids = {sq["id"] for sq in sub_questions}
    for sq in sub_questions:
        sq["depends_on"] = [d for d in sq["depends_on"] if d in valid_ids]
    return sub_questions


def build_dag_from_decomposition(
    root_query: str,
    sub_questions: list[dict],
) -> PlanDAG:
    """
    Construct a PlanDAG from validated sub-question dicts.
    Adds all nodes first, then all edges.
    """
    dag = PlanDAG()

    # Add nodes
    for sq in sub_questions:
        node = DAGNode(
            node_id=sq["id"],
            question=sq["question"],
        )
        dag.add_node(node)

    # Add edges (dependencies)
    for sq in sub_questions:
        for dep_id in sq["depends_on"]:
            try:
                dag.add_edge(dep_id, sq["id"])
            except ValueError:
                # Skip edges that would create cycles
                continue

    return dag


async def decompose_query(
    query: str,
    llm_client,
    prompt_template: str = DECOMPOSITION_PROMPT,
) -> tuple[PlanDAG, list[dict]]:
    """
    Full decomposition pipeline:
    1. Detect complexity (heuristic)
    2. Call LLM to propose sub-questions
    3. Parse and validate the response
    4. Build the DAG

    Returns (dag, sub_questions) tuple.
    Falls back to a single-node DAG if LLM decomposition fails.
    """
    complexity = detect_complexity(query)

    # Build prompt
    prompt = prompt_template.format(query=query)

    # Call LLM
    raw_response = await llm_client.complete(
        prompt=prompt,
        system="You are a research planning assistant. Return only valid JSON.",
        temperature=0.3,  # Low temperature for structured output
    )

    # Parse response
    sub_questions = parse_decomposition_response(raw_response)

    # Validate dependencies
    sub_questions = validate_dependencies(sub_questions)

    # Fallback: if parsing failed or returned nothing, create single node
    if not sub_questions:
        sub_questions = [{
            "id": "sub_1",
            "question": query,
            "depends_on": [],
        }]

    # Build DAG
    dag = build_dag_from_decomposition(query, sub_questions)

    return dag, sub_questions