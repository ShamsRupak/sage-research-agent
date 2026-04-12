"""
SAGE Demo Runner — end-to-end demonstration with rich terminal output.

Runs SAGE on a complex research query and displays the full agent loop:
planner decisions, ReAct steps, Critic interventions, and final synthesis.

Usage:
    python -m demo.run_demo
"""

import asyncio
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from sage.agent import SAGEAgent
from sage.synthesis.synthesizer import synthesize_report
from sage.llm.client import LLMClient


console = Console()

# ─── Demo Queries ─────────────────────────────────────────────
# Pick one to run, or pass a custom query as a command-line argument.

DEMO_QUERIES = [
    (
        "Analyze the trade-offs between transformer-based and recurrent "
        "architectures for long-context reasoning, citing empirical evidence "
        "and identifying open research questions."
    ),
    (
        "What are the current approaches to reducing hallucination in large "
        "language models, and how effective are they based on recent benchmarks?"
    ),
    (
        "Compare the environmental impact of lithium-ion batteries versus "
        "solid-state batteries for electric vehicles, considering manufacturing, "
        "lifecycle emissions, and recyclability."
    ),
]


async def run_demo(query: str | None = None) -> None:
    """Run SAGE on a demo query and display results."""

    # Select query
    if query is None:
        query = DEMO_QUERIES[0]

    console.print()
    console.print(Panel(
        "[bold cyan]SAGE — Self-Adaptive Goal-directed Executor[/bold cyan]\n\n"
        "[dim]A multi-tool LLM agent with hierarchical planning "
        "and evidence-guided reasoning[/dim]",
        border_style="bold cyan",
        padding=(1, 2),
    ))

    # Initialize agent
    console.print("\n[bold]Initializing SAGE agent...[/bold]")
    llm_client = LLMClient()
    agent = SAGEAgent(
        llm_client=llm_client,
        max_iterations=30,
        max_react_steps=5,
        confidence_threshold=0.70,
        verbose=True,
    )

    # Run the agent
    console.print(f"[bold]Running on query:[/bold] {query}\n")

    try:
        state = await agent.run(query)
    except Exception as e:
        console.print(f"\n[bold red]Agent failed with error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        return

    # Get the DAG for synthesis
    # Re-decompose to get the DAG (it's not stored on state, so we rebuild)
    # In a production system you'd store the DAG on the agent or state
    from sage.planner.decomposer import decompose_query
    dag, _ = await decompose_query(query, llm_client)
    state.record_llm_call()

    # Synthesize final report
    console.print("\n[bold yellow]━━━ SYNTHESIS: Generating final report... ━━━[/bold yellow]")

    try:
        report = await synthesize_report(dag, state, llm_client)
    except Exception as e:
        console.print(f"\n[bold red]Synthesis failed: {e}[/bold red]")
        # Fallback: manual report from evidence
        report = _fallback_report(state)

    # Display the report
    console.print()
    console.print(Panel(
        Markdown(report),
        title="[bold green]Final Research Synthesis[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    # Display usage stats
    usage = llm_client.get_usage_summary()
    console.print()
    console.print(Panel(
        f"[bold]LLM Calls:[/bold] {usage['total_calls']}\n"
        f"[bold]Failed Calls:[/bold] {usage['failed_calls']}\n"
        f"[bold]Total Tokens:[/bold] ~{usage['total_tokens']:,}\n"
        f"[bold]Tool Calls:[/bold] {state.total_tool_calls}\n"
        f"[bold]Iterations:[/bold] {state.iteration_count}\n"
        f"[bold]Elapsed:[/bold] {state.summary()['elapsed_seconds']}s",
        title="[bold cyan]Usage Summary[/bold cyan]",
        border_style="cyan",
    ))

    # Save report to file
    report_path = "demo_output.md"
    with open(report_path, "w") as f:
        f.write(report)
    console.print(f"\n[dim]Report saved to {report_path}[/dim]")


def _fallback_report(state) -> str:
    """Generate a basic report if LLM synthesis fails."""
    lines = [
        f"# Research Report\n",
        f"**Query:** {state.root_query}\n",
        f"---\n",
    ]
    for node_id, node_state in state.nodes.items():
        lines.append(f"## {node_id}: {node_state.question}\n")
        lines.append(f"**Status:** {node_state.status.value} | "
                     f"**Confidence:** {node_state.confidence:.2f}\n")
        if node_state.answer:
            lines.append(f"{node_state.answer[:1000]}\n")
        lines.append("---\n")

    summary = state.summary()
    lines.append(f"\n**LLM Calls:** {summary['total_llm_calls']} | "
                 f"**Tool Calls:** {summary['total_tool_calls']} | "
                 f"**Elapsed:** {summary['elapsed_seconds']}s\n")
    return "\n".join(lines)


def main():
    """Entry point for the demo."""
    # Check for custom query from command line
    query = None
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])

    asyncio.run(run_demo(query))


if __name__ == "__main__":
    main()