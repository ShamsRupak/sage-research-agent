"""
SAGE Evaluation Rubric — scoring helpers for comparing agent outputs.

Measures structural quality, self-correction behavior, and output
characteristics across different agent configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from sage.memory.state import AgentState, NodeStatus


@dataclass
class EvalMetrics:
    """Metrics collected from a single agent run."""
    query_id: str
    condition: str  # "sage", "flat_react", or "single_llm"
    query: str = ""

    # Execution metrics
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    iterations: int = 0
    elapsed_seconds: float = 0.0

    # Planning metrics
    num_subgoals: int = 0
    num_resolved: int = 0
    num_failed: int = 0
    num_replans: int = 0

    # Quality metrics
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0
    num_retries: int = 0
    num_contradictions: int = 0

    # Output metrics
    report_length: int = 0
    num_citations: int = 0
    has_provenance: bool = False
    has_confidence_scores: bool = False
    has_contradiction_analysis: bool = False


def extract_metrics(
    query_id: str,
    condition: str,
    state: AgentState,
    report: str = "",
) -> EvalMetrics:
    """Extract evaluation metrics from a completed agent run."""
    summary = state.summary()

    # Compute confidence stats
    confidences = [
        n.confidence for n in state.nodes.values()
        if n.status == NodeStatus.RESOLVED
    ]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    min_conf = min(confidences) if confidences else 0.0
    max_conf = max(confidences) if confidences else 0.0

    # Count retries and replans
    total_retries = sum(n.retry_count for n in state.nodes.values())
    num_replans = sum(
        1 for n in state.nodes.values()
        if n.status == NodeStatus.ESCALATED
        or any(
            v.signal == "ESCALATE" for v in n.critic_verdicts
        )
    )

    # Count contradictions
    total_contradictions = sum(
        len(v.contradictions)
        for n in state.nodes.values()
        for v in n.critic_verdicts
    )

    # Output quality signals
    num_citations = report.count("http://") + report.count("https://")

    return EvalMetrics(
        query_id=query_id,
        condition=condition,
        query=state.root_query,
        total_llm_calls=summary["total_llm_calls"],
        total_tool_calls=summary["total_tool_calls"],
        iterations=summary["iterations"],
        elapsed_seconds=summary["elapsed_seconds"],
        num_subgoals=summary["total_nodes"],
        num_resolved=summary["resolved"],
        num_failed=summary["pending"],
        num_replans=num_replans,
        avg_confidence=round(avg_conf, 3),
        min_confidence=round(min_conf, 3),
        max_confidence=round(max_conf, 3),
        num_retries=total_retries,
        num_contradictions=total_contradictions,
        report_length=len(report),
        num_citations=num_citations,
        has_provenance=len(state.all_provenance) > 0,
        has_confidence_scores=len(confidences) > 0,
        has_contradiction_analysis=total_contradictions > 0,
    )


def format_metrics_table(metrics_list: list[EvalMetrics]) -> str:
    """Format a list of metrics into a readable comparison table."""
    lines = []
    lines.append(
        f"{'Query':<6} {'Condition':<14} {'Nodes':>5} {'Resolved':>8} "
        f"{'LLM':>5} {'Tools':>5} {'AvgConf':>8} {'Retries':>7} "
        f"{'Replans':>7} {'Cites':>5} {'Length':>7} {'Time(s)':>8}"
    )
    lines.append("─" * 105)

    for m in metrics_list:
        lines.append(
            f"{m.query_id:<6} {m.condition:<14} {m.num_subgoals:>5} "
            f"{m.num_resolved:>8} {m.total_llm_calls:>5} "
            f"{m.total_tool_calls:>5} {m.avg_confidence:>8.3f} "
            f"{m.num_retries:>7} {m.num_replans:>7} "
            f"{m.num_citations:>5} {m.report_length:>7} "
            f"{m.elapsed_seconds:>8.1f}"
        )

    return "\n".join(lines)


def format_comparison_summary(metrics_list: list[EvalMetrics]) -> str:
    """Produce a summary comparing conditions across all queries."""
    conditions = {}
    for m in metrics_list:
        if m.condition not in conditions:
            conditions[m.condition] = []
        conditions[m.condition].append(m)

    lines = ["\n=== Condition Summary ===\n"]

    for cond, runs in conditions.items():
        n = len(runs)
        avg_conf = sum(r.avg_confidence for r in runs) / n if n else 0
        avg_tools = sum(r.total_tool_calls for r in runs) / n if n else 0
        avg_cites = sum(r.num_citations for r in runs) / n if n else 0
        avg_len = sum(r.report_length for r in runs) / n if n else 0
        avg_time = sum(r.elapsed_seconds for r in runs) / n if n else 0
        total_retries = sum(r.num_retries for r in runs)
        total_replans = sum(r.num_replans for r in runs)

        lines.append(f"  {cond}:")
        lines.append(f"    Avg Confidence:  {avg_conf:.3f}")
        lines.append(f"    Avg Tool Calls:  {avg_tools:.1f}")
        lines.append(f"    Avg Citations:   {avg_cites:.1f}")
        lines.append(f"    Avg Report Len:  {avg_len:.0f} chars")
        lines.append(f"    Avg Time:        {avg_time:.1f}s")
        lines.append(f"    Total Retries:   {total_retries}")
        lines.append(f"    Total Re-plans:  {total_replans}")
        lines.append("")

    return "\n".join(lines)