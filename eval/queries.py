"""
SAGE Evaluation Queries — diverse test queries at varying complexity.

Each query is tagged with difficulty level and expected characteristics
to help interpret ablation results.
"""

EVAL_QUERIES = [
    {
        "id": "q1",
        "query": (
            "Analyze the trade-offs between transformer-based and recurrent "
            "architectures for long-context reasoning, citing empirical evidence "
            "and identifying open research questions."
        ),
        "difficulty": "hard",
        "expected_subgoals": "4-6",
        "notes": "Multi-faceted comparison requiring evidence from multiple sources",
    },
    {
        "id": "q2",
        "query": (
            "What are the current approaches to reducing hallucination in large "
            "language models, and how effective are they based on recent benchmarks?"
        ),
        "difficulty": "hard",
        "expected_subgoals": "3-5",
        "notes": "Requires recent evidence and benchmark data",
    },
    {
        "id": "q3",
        "query": (
            "Compare the environmental impact of lithium-ion batteries versus "
            "solid-state batteries for electric vehicles, considering manufacturing, "
            "lifecycle emissions, and recyclability."
        ),
        "difficulty": "hard",
        "expected_subgoals": "4-6",
        "notes": "Cross-domain comparison with multiple evaluation axes",
    },
    {
        "id": "q4",
        "query": (
            "What is the current state of quantum error correction, and what "
            "are the main obstacles to achieving fault-tolerant quantum computing?"
        ),
        "difficulty": "medium",
        "expected_subgoals": "3-4",
        "notes": "Technical topic with well-defined sub-components",
    },
    {
        "id": "q5",
        "query": (
            "How does retrieval-augmented generation (RAG) compare to fine-tuning "
            "for domain-specific language model applications?"
        ),
        "difficulty": "medium",
        "expected_subgoals": "3-4",
        "notes": "Focused comparison with practical implications",
    },
]


def get_query(query_id: str) -> dict | None:
    """Look up a query by ID."""
    for q in EVAL_QUERIES:
        if q["id"] == query_id:
            return q
    return None


def get_all_queries() -> list[dict]:
    """Return all evaluation queries."""
    return EVAL_QUERIES