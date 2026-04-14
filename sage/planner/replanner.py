"""
SAGE Re-planner — inserts new sub-goals when the Critic escalates.

When the Evidence Critic emits ESCALATE, it provides a rationale explaining
what information is missing or contradictory. The re-planner uses a single
LLM call to propose new sub-questions that address the gap, then
deterministically inserts them into the existing DAG with proper edges.
"""

from __future__ import annotations

import json
import re
from sage.planner.dag import DAGNode, PlanDAG
from sage.planner.decomposer import parse_decomposition_response, validate_dependencies


REPLAN_PROMPT = """You are a research planning assistant. A previous research step failed to gather sufficient evidence.

Original question: {root_query}
Failed sub-question: {failed_question}
Critic's rationale: {rationale}
Evidence gathered so far: {evidence_summary}

Propose 1-3 NEW sub-questions that address the gap identified by the critic. These should target the specific missing information.

Rules:
1. Each sub-question must be specific and independently answerable
2. Do not repeat the failed question — refine or decompose it further
3. Return ONLY valid JSON

Return this exact JSON format:
{{
  "sub_questions": [
    {{
      "id": "replan_1",
      "question": "A new, more targeted sub-question",
      "depends_on": []
    }}
  ]
}}"""


def generate_replan_node_id(dag: PlanDAG, prefix: str = "replan") -> str:
    """Generate a unique node ID for a re-planned sub-goal."""
    existing = set(dag.nodes.keys())
    counter = 1
    while f"{prefix}_{counter}" in existing:
        counter += 1
    return f"{prefix}_{counter}"


async def replan(
    dag: PlanDAG,
    failed_node_id: str,
    rationale: str,
    evidence_summary: str,
    root_query: str,
    llm_client,
) -> list[str]:
    """
    Insert new sub-goals into the DAG to address an ESCALATE signal.

    Steps:
    1. Build a re-planning prompt with context about the failure
    2. Call LLM for new sub-question proposals
    3. Parse and validate
    4. Insert new nodes into the DAG with edges from the failed node's dependencies
    5. Return the list of new node IDs

    Returns empty list if re-planning fails.
    """
    failed_node = dag.get_node(failed_node_id)

    prompt = REPLAN_PROMPT.format(
        root_query=root_query,
        failed_question=failed_node.question,
        rationale=rationale,
        evidence_summary=evidence_summary[:2000],  # Truncate to avoid token limits
    )

    raw_response = await llm_client.complete(
        prompt=prompt,
        system="You are a research planning assistant. Return only valid JSON.",
        temperature=0.3,
    )

    sub_questions = parse_decomposition_response(raw_response)

    if not sub_questions:
        return []

    # Assign unique IDs
    new_node_ids = []
    used_ids = set(dag.nodes.keys())
    for sq in sub_questions:
        counter = 1
        while f"replan_{counter}" in used_ids:
            counter += 1
        new_id = f"replan_{counter}"
        used_ids.add(new_id)
        sq["id"] = new_id
        # New nodes depend on the same things the failed node depended on
        # but NOT on the failed node itself
        sq["depends_on"] = [
            d for d in failed_node.dependencies
            if d != failed_node_id
        ]
        new_node_ids.append(new_id)

    sub_questions = validate_dependencies(sub_questions)

    # Insert into DAG
    for sq in sub_questions:
        node = DAGNode(
            node_id=sq["id"],
            question=sq["question"],
            metadata={"origin": "replan", "triggered_by": failed_node_id},
        )
        dag.add_node(node)

        for dep_id in sq["depends_on"]:
            try:
                dag.add_edge(dep_id, sq["id"])
            except ValueError:
                continue

    return new_node_ids