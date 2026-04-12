"""
SAGE Ablation Study — compares three conditions:

1. Full SAGE: DAG planner + ReAct + Evidence Critic
2. Flat ReAct: Single-node ReAct loop with no planner or Critic
3. Single LLM: One LLM call with no tools or planning

This directly demonstrates the value of the planning and critique layers.

Usage:
    python -m eval.ablation                  # Run all queries, all conditions
    python -m eval.ablation --query q5       # Run one query
    python -m eval.ablation --condition sage # Run one condition on all queries
"""

from __future__ import annotations

import asyncio
import argparse
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from sage.llm.client import LLMClient
from sage.agent import SAGEAgent
from sage.memory.state import AgentState, NodeStatus, ToolCall, ReasoningStep
from sage.tools.registry import ToolRegistry
from sage.tools.web_search import web_search
from sage.tools.fetch_url import fetch_url
from sage.tools.code_runner import code_run
from sage.llm.prompts import REACT_SYSTEM, REACT_USER
from sage.llm.parser import parse_react_response
from sage.synthesis.synthesizer import synthesize_report
from sage.planner.dag import PlanDAG, DAGNode
from eval.queries import EVAL_QUERIES, get_query
from eval.rubric import extract_metrics, format_metrics_table, format_comparison_summary, EvalMetrics

console = Console()


# ─── Condition 1: Full SAGE ──────────────────────────────────

async def run_sage(query: str, query_id: str) -> tuple[EvalMetrics, str]:
    """Run full SAGE agent on a query."""
    console.print(f"\n[bold cyan]── SAGE (full) on {query_id} ──[/bold cyan]")

    llm_client = LLMClient()
    agent = SAGEAgent(
        llm_client=llm_client,
        max_iterations=30,
        max_react_steps=5,
        confidence_threshold=0.70,
        verbose=False,
    )

    state = await agent.run(query)

    # Synthesize report
    from sage.planner.decomposer import decompose_query
    dag, _ = await decompose_query(query, llm_client)
    state.record_llm_call()

    try:
        report = await synthesize_report(dag, state, llm_client)
    except Exception:
        report = _fallback_report(state)

    metrics = extract_metrics(query_id, "sage", state, report)
    console.print(f"  [green]✓ Done[/green] — {metrics.elapsed_seconds:.1f}s, "
                  f"conf={metrics.avg_confidence:.2f}")
    return metrics, report


# ─── Condition 2: Flat ReAct (no planner, no critic) ─────────

async def run_flat_react(query: str, query_id: str) -> tuple[EvalMetrics, str]:
    """
    Run a flat ReAct loop — single node, no DAG, no Critic.
    This isolates the contribution of the planning and critique layers.
    """
    console.print(f"\n[bold yellow]── Flat ReAct on {query_id} ──[/bold yellow]")

    llm_client = LLMClient()
    state = AgentState(root_query=query)
    state.register_node("flat_1", query)
    node_state = state.get_node("flat_1")
    node_state.status = NodeStatus.IN_PROGRESS

    # Build a simple tool registry (no LLM-dependent tools to keep it fair)
    registry = ToolRegistry()
    registry.register("web_search", "Search the web", '{"query": "..."}', web_search)
    registry.register("fetch_url", "Fetch a URL", '{"url": "..."}', fetch_url)
    registry.register("code_run", "Run Python code", '{"snippet": "..."}', code_run)

    # Run ReAct loop for up to 8 steps (more steps since no planning)
    max_steps = 8
    history = ""

    for step in range(max_steps):
        tool_descriptions = registry.get_descriptions()
        prompt = REACT_USER.format(
            question=query,
            history=history if history else "(No previous steps)",
            context="(No context — flat execution mode)",
        )
        system = REACT_SYSTEM.format(tool_descriptions=tool_descriptions)

        raw = await llm_client.complete(prompt=prompt, system=system, temperature=0.5)
        state.record_llm_call()

        parsed = parse_react_response(raw)
        if parsed is None:
            break

        reasoning_step = ReasoningStep(
            thought=parsed.thought,
            action=parsed.action,
            action_input=parsed.action_input,
        )

        if parsed.action == "finish":
            answer = parsed.action_input.get("answer", parsed.thought)
            node_state.answer = answer
            node_state.evidence.append(answer)
            reasoning_step.observation = answer
            node_state.reasoning_trace.append(reasoning_step)
            break

        tool_result = await registry.dispatch(parsed.action, parsed.action_input)

        tool_call = ToolCall(
            tool_name=parsed.action,
            tool_input=parsed.action_input,
            result=tool_result,
        )
        state.record_tool_call("flat_1", tool_call)

        observation = tool_result["content"]
        reasoning_step.observation = observation
        node_state.reasoning_trace.append(reasoning_step)

        if tool_result["success"]:
            node_state.evidence.append(observation)

        history += (
            f"\nStep {step + 1}:\n"
            f"Thought: {parsed.thought}\n"
            f"Action: {parsed.action}\n"
            f"Observation: {observation[:500]}\n"
        )

    # Mark as resolved (no Critic to judge)
    node_state.status = NodeStatus.RESOLVED
    node_state.confidence = 0.5  # No Critic — assign neutral confidence

    # Synthesize a basic report
    state.finalize()
    report = _build_flat_report(state)

    metrics = extract_metrics(query_id, "flat_react", state, report)
    console.print(f"  [green]✓ Done[/green] — {metrics.elapsed_seconds:.1f}s")
    return metrics, report


# ─── Condition 3: Single LLM Call ────────────────────────────

async def run_single_llm(query: str, query_id: str) -> tuple[EvalMetrics, str]:
    """
    Single LLM call with no tools, no planning, no critique.
    This is the baseline that SAGE is designed to improve upon.
    """
    console.print(f"\n[bold red]── Single LLM on {query_id} ──[/bold red]")

    llm_client = LLMClient()
    state = AgentState(root_query=query)
    state.register_node("single_1", query)
    node_state = state.get_node("single_1")

    prompt = (
        f"Please provide a thorough analysis of the following research question. "
        f"Include empirical evidence where possible, discuss trade-offs, and "
        f"identify open questions.\n\n"
        f"Question: {query}"
    )

    start = time.time()
    response = await llm_client.complete(
        prompt=prompt,
        system="You are a research analyst. Provide thorough, well-structured analysis.",
        temperature=0.7,
        max_tokens=4096,
    )
    elapsed = time.time() - start

    state.record_llm_call()
    node_state.answer = response
    node_state.evidence = [response]
    node_state.status = NodeStatus.RESOLVED
    node_state.confidence = 0.0  # No verification at all
    state.finalize()

    report = f"# Research Analysis\n\n**Query:** {query}\n\n---\n\n{response}"

    metrics = extract_metrics(query_id, "single_llm", state, report)
    metrics.elapsed_seconds = round(elapsed, 2)
    console.print(f"  [green]✓ Done[/green] — {metrics.elapsed_seconds:.1f}s")
    return metrics, report


# ─── Helpers ─────────────────────────────────────────────────

def _fallback_report(state: AgentState) -> str:
    lines = [f"# Report\n\n**Query:** {state.root_query}\n\n---\n"]
    for nid, ns in state.nodes.items():
        lines.append(f"## {nid}: {ns.question}\n")
        if ns.answer:
            lines.append(f"{ns.answer[:1000]}\n\n")
    return "\n".join(lines)


def _build_flat_report(state: AgentState) -> str:
    lines = [f"# Flat ReAct Report\n\n**Query:** {state.root_query}\n\n---\n"]
    for nid, ns in state.nodes.items():
        if ns.answer:
            lines.append(ns.answer)
    return "\n".join(lines)


# ─── Main Runner ─────────────────────────────────────────────

async def run_ablation(
    query_ids: list[str] | None = None,
    conditions: list[str] | None = None,
) -> list[EvalMetrics]:
    """
    Run the ablation study across specified queries and conditions.
    Returns a list of EvalMetrics for analysis.
    """
    if query_ids is None:
        query_ids = [q["id"] for q in EVAL_QUERIES]
    if conditions is None:
        conditions = ["sage", "flat_react", "single_llm"]

    all_metrics: list[EvalMetrics] = []

    condition_runners = {
        "sage": run_sage,
        "flat_react": run_flat_react,
        "single_llm": run_single_llm,
    }

    for qid in query_ids:
        q = get_query(qid)
        if q is None:
            console.print(f"[red]Unknown query ID: {qid}[/red]")
            continue

        console.print(f"\n[bold]{'='*60}[/bold]")
        console.print(f"[bold]Query {q['id']}: {q['query'][:80]}...[/bold]")
        console.print(f"[dim]Difficulty: {q['difficulty']}[/dim]")

        for cond in conditions:
            runner = condition_runners.get(cond)
            if runner is None:
                console.print(f"[red]Unknown condition: {cond}[/red]")
                continue

            try:
                metrics, report = await runner(q["query"], q["id"])
                all_metrics.append(metrics)

                # Save individual report
                os.makedirs("eval_outputs", exist_ok=True)
                report_path = f"eval_outputs/{qid}_{cond}.md"
                with open(report_path, "w") as f:
                    f.write(report)

            except Exception as e:
                console.print(f"  [bold red]✗ {cond} failed: {e}[/bold red]")
                import traceback
                traceback.print_exc()

            # Rate limit buffer between runs
            await asyncio.sleep(5)

    return all_metrics


def display_results(metrics: list[EvalMetrics]) -> None:
    """Display ablation results in a rich table."""
    table = Table(
        title="Ablation Study Results",
        box=box.ROUNDED,
        show_lines=True,
        title_style="bold cyan",
    )
    table.add_column("Query", style="cyan", width=6)
    table.add_column("Condition", style="bold", width=12)
    table.add_column("Nodes", justify="right", width=5)
    table.add_column("Resolved", justify="right", width=8)
    table.add_column("LLM Calls", justify="right", width=9)
    table.add_column("Tool Calls", justify="right", width=10)
    table.add_column("Avg Conf", justify="right", width=8)
    table.add_column("Retries", justify="right", width=7)
    table.add_column("Re-plans", justify="right", width=8)
    table.add_column("Citations", justify="right", width=9)
    table.add_column("Report Len", justify="right", width=10)
    table.add_column("Time (s)", justify="right", width=8)

    for m in metrics:
        cond_style = {
            "sage": "green",
            "flat_react": "yellow",
            "single_llm": "red",
        }.get(m.condition, "white")

        table.add_row(
            m.query_id,
            f"[{cond_style}]{m.condition}[/{cond_style}]",
            str(m.num_subgoals),
            str(m.num_resolved),
            str(m.total_llm_calls),
            str(m.total_tool_calls),
            f"{m.avg_confidence:.2f}",
            str(m.num_retries),
            str(m.num_replans),
            str(m.num_citations),
            str(m.report_length),
            f"{m.elapsed_seconds:.1f}",
        )

    console.print()
    console.print(table)

    # Print comparison summary
    summary = format_comparison_summary(metrics)
    console.print(summary)


async def main():
    parser = argparse.ArgumentParser(description="SAGE Ablation Study")
    parser.add_argument(
        "--query", type=str, default=None,
        help="Run a specific query ID (e.g., q1, q2). Default: all queries.",
    )
    parser.add_argument(
        "--condition", type=str, default=None,
        help="Run a specific condition (sage, flat_react, single_llm). Default: all.",
    )
    args = parser.parse_args()

    query_ids = [args.query] if args.query else None
    conditions = [args.condition] if args.condition else None

    console.print(Panel(
        "[bold cyan]SAGE Ablation Study[/bold cyan]\n\n"
        "[dim]Comparing: Full SAGE vs Flat ReAct vs Single LLM[/dim]",
        border_style="cyan",
    ))

    metrics = await run_ablation(query_ids, conditions)

    if metrics:
        display_results(metrics)

        # Save results
        os.makedirs("eval_outputs", exist_ok=True)
        with open("eval_outputs/ablation_results.txt", "w") as f:
            f.write(format_metrics_table(metrics))
            f.write("\n\n")
            f.write(format_comparison_summary(metrics))
        console.print("\n[dim]Results saved to eval_outputs/ablation_results.txt[/dim]")


if __name__ == "__main__":
    asyncio.run(main())