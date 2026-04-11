"""
SAGE Agent — master orchestrator wiring all modules together.

The agent loop:
1. Decompose query into DAG of sub-goals
2. Schedule sub-goals by priority
3. For each sub-goal, run a ReAct inner loop (LLM → tool → observe)
4. After each sub-goal, call the Evidence Critic
5. Handle Critic signals: ACCEPT → next node, RETRY → re-run, ESCALATE → re-plan
6. When all nodes resolved, synthesize final report

All high-level control flow is deterministic Python.
The LLM is invoked only for per-step reasoning and tool proposals.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from sage.memory.state import (
    AgentState,
    NodeStatus,
    ToolCall,
    ReasoningStep,
    ProvenanceRecord,
)
from sage.planner.dag import PlanDAG
from sage.planner.decomposer import decompose_query
from sage.planner.scheduler import Scheduler
from sage.planner.replanner import replan
from sage.critic.evidence_critic import EvidenceCritic, apply_verdict
from sage.llm.client import LLMClient
from sage.llm.prompts import REACT_SYSTEM, REACT_USER
from sage.llm.parser import parse_react_response
from sage.tools.registry import ToolRegistry
from sage.tools.web_search import web_search
from sage.tools.fetch_url import fetch_url
from sage.tools.extract_claims import extract_claims
from sage.tools.code_runner import code_run
from sage.tools.cross_reference import cross_reference

console = Console()


def build_tool_registry(llm_client: LLMClient) -> ToolRegistry:
    """Create and populate the tool registry with all available tools."""
    registry = ToolRegistry()

    registry.register(
        name="web_search",
        description="Search the web for information. Returns ranked snippets from multiple sources.",
        parameters='{"query": "your search query string"}',
        func=web_search,
    )

    registry.register(
        name="fetch_url",
        description="Fetch and extract text content from a specific URL.",
        parameters='{"url": "https://example.com"}',
        func=fetch_url,
    )

    # extract_claims and cross_reference need the LLM client
    # Wrap them to inject the client automatically
    async def _extract_claims(text: str, **kwargs) -> dict:
        return await extract_claims(text=text, llm_client=llm_client)

    async def _cross_reference(claims: list | str, **kwargs) -> dict:
        return await cross_reference(claims=claims, llm_client=llm_client)

    registry.register(
        name="extract_claims",
        description="Extract key factual claims from a block of text. Returns structured claims with confidence scores.",
        parameters='{"text": "the text to extract claims from"}',
        func=_extract_claims,
    )

    registry.register(
        name="code_run",
        description="Execute a Python code snippet and return its output. Use for calculations or data processing.",
        parameters='{"snippet": "print(2+2)"}',
        func=code_run,
    )

    registry.register(
        name="cross_reference",
        description="Check a list of claims for internal consistency and contradictions.",
        parameters='{"claims": ["claim 1", "claim 2"]}',
        func=_cross_reference,
    )

    return registry


class SAGEAgent:
    """
    The SAGE agent: decomposes, plans, executes, critiques, and synthesizes.

    Usage:
        agent = SAGEAgent()
        result = await agent.run("Your complex research question here")
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        max_iterations: int = 50,
        max_react_steps: int = 6,
        confidence_threshold: float = 0.75,
        verbose: bool = True,
    ) -> None:
        self.llm_client = llm_client or LLMClient()
        self.max_iterations = max_iterations
        self.max_react_steps = max_react_steps
        self.confidence_threshold = confidence_threshold
        self.verbose = verbose
        self.registry = build_tool_registry(self.llm_client)
        self.critic = EvidenceCritic(
            self.llm_client,
            confidence_threshold=confidence_threshold,
        )

    async def run(self, query: str) -> AgentState:
        """
        Execute the full SAGE pipeline on a research query.

        Returns the final AgentState containing all evidence,
        reasoning traces, and the synthesis report.
        """
        # ── Step 1: Initialize State ──
        state = AgentState(
            root_query=query,
            max_iterations=self.max_iterations,
            confidence_threshold=self.confidence_threshold,
        )

        self._log_header(query)

        # ── Step 2: Decompose Query into DAG ──
        self._log_phase("PLANNING", "Decomposing query into sub-goals...")
        dag, sub_questions = await decompose_query(query, self.llm_client)
        state.record_llm_call()

        # Register all nodes in state
        for sq in sub_questions:
            state.register_node(sq["id"], sq["question"])

        self._log_dag(dag)

        # ── Step 3: Initialize Scheduler ──
        scheduler = Scheduler(dag, state)
        scheduler.initialize()

        # ── Step 4: Main Agent Loop ──
        self._log_phase("EXECUTION", "Starting agent loop...")

        while state.iteration_count < state.max_iterations:
            state.iteration_count += 1

            # Check termination conditions
            if state.all_resolved():
                self._log_phase("COMPLETE", "All sub-goals resolved!")
                break

            # Get next node from scheduler
            next_node_id = scheduler.get_next()
            if next_node_id is None:
                # No ready nodes — check if we're stuck
                if not scheduler.has_pending():
                    break
                # There are pending nodes but none are ready (deps not met)
                # This shouldn't happen in a well-formed DAG, but safety check
                self._log_warning("No ready nodes but pending nodes exist. Breaking.")
                break

            node_state = state.get_node(next_node_id)
            node_state.status = NodeStatus.IN_PROGRESS

            self._log_node_start(next_node_id, node_state.question, state.iteration_count)

            # ── Step 4a: Execute ReAct Loop for this sub-goal ──
            await self._execute_react_loop(next_node_id, dag, state)

            # ── Step 4b: Call Evidence Critic ──
            self._log_critic_start(next_node_id)
            verdict = await self.critic.evaluate(node_state, state)
            self._log_critic_result(verdict)

            # ── Step 4c: Handle Critic Signal ──
            signal = apply_verdict(verdict, node_state, state)

            if signal == "ACCEPT":
                self._log_signal("ACCEPT", next_node_id, verdict.confidence)

            elif signal == "RETRY":
                self._log_signal("RETRY", next_node_id, verdict.confidence)
                scheduler.reprioritize(next_node_id, 0.01)  # High priority for retry

            elif signal == "ESCALATE":
                self._log_signal("ESCALATE", next_node_id, verdict.confidence)

                # ── Step 4d: Re-plan ──
                evidence_summary = "\n".join(node_state.evidence[:3])
                new_node_ids = await replan(
                    dag=dag,
                    failed_node_id=next_node_id,
                    rationale=verdict.rationale,
                    evidence_summary=evidence_summary,
                    root_query=query,
                    llm_client=self.llm_client,
                )
                state.record_llm_call()

                # Register new nodes and add to scheduler
                for nid in new_node_ids:
                    new_node = dag.get_node(nid)
                    state.register_node(nid, new_node.question)
                    scheduler.add_node(nid)
                    self._log_replan_node(nid, new_node.question)

                # Mark the failed node as failed (don't retry it)
                node_state.status = NodeStatus.FAILED

        # ── Step 5: Finalize ──
        state.finalize()
        self._log_summary(state)

        return state

    async def _execute_react_loop(
        self,
        node_id: str,
        dag: PlanDAG,
        state: AgentState,
    ) -> None:
        """
        Run the ReAct inner loop for a single sub-goal.

        The LLM proposes tool calls or a final answer. The agent executes
        the tools and feeds observations back. This repeats until the LLM
        says "finish" or the max steps are reached.
        """
        node_state = state.get_node(node_id)

        # Build context from resolved dependencies
        context = self._build_context(node_id, dag, state)

        # Build history of prior steps (for retries)
        history = ""

        for step_num in range(self.max_react_steps):
            # Build the ReAct prompt
            tool_descriptions = self.registry.get_descriptions()
            prompt = REACT_USER.format(
                question=node_state.question,
                history=history if history else "(No previous steps)",
                context=context if context else "(No context from other sub-goals)",
            )
            system = REACT_SYSTEM.format(tool_descriptions=tool_descriptions)

            # Call LLM
            raw_response = await self.llm_client.complete(
                prompt=prompt,
                system=system,
                temperature=0.5,
            )
            state.record_llm_call()

            # Parse the response
            parsed = parse_react_response(raw_response)
            if parsed is None:
                self._log_warning(f"Failed to parse ReAct response for {node_id}")
                break

            self._log_react_step(step_num + 1, parsed.thought, parsed.action)

            # Record reasoning step
            reasoning_step = ReasoningStep(
                thought=parsed.thought,
                action=parsed.action,
                action_input=parsed.action_input,
            )

            # Check if LLM wants to finish
            if parsed.action == "finish":
                answer = parsed.action_input.get("answer", parsed.thought)
                node_state.answer = answer
                node_state.evidence.append(answer)
                reasoning_step.observation = answer
                node_state.reasoning_trace.append(reasoning_step)
                self._log_react_finish(answer[:200])
                break

            # Execute the tool
            tool_result = await self.registry.dispatch(
                parsed.action, parsed.action_input
            )

            # Record tool call
            tool_call = ToolCall(
                tool_name=parsed.action,
                tool_input=parsed.action_input,
                result=tool_result,
            )
            state.record_tool_call(node_id, tool_call)

            # Record observation
            observation = tool_result["content"]
            reasoning_step.observation = observation
            node_state.reasoning_trace.append(reasoning_step)

            # Add successful results to evidence
            if tool_result["success"]:
                node_state.evidence.append(observation)

                # Track provenance for web search results
                urls = tool_result.get("metadata", {}).get("urls", [])
                for url in urls:
                    node_state.provenance.append(
                        ProvenanceRecord(
                            claim=observation[:200],
                            source_url=url,
                            tool_call=tool_call,
                            node_id=node_id,
                        )
                    )
                    state.all_provenance.append(
                        ProvenanceRecord(
                            claim=observation[:200],
                            source_url=url,
                            tool_call=tool_call,
                            node_id=node_id,
                        )
                    )

            self._log_tool_result(parsed.action, tool_result["success"])

            # Update history for next iteration
            history += (
                f"\nStep {step_num + 1}:\n"
                f"Thought: {parsed.thought}\n"
                f"Action: {parsed.action}\n"
                f"Observation: {observation[:500]}\n"
            )

        else:
            # Max steps reached without finish
            if node_state.evidence:
                node_state.answer = "\n".join(node_state.evidence[:3])
            self._log_warning(
                f"Max ReAct steps ({self.max_react_steps}) reached for {node_id}"
            )

    def _build_context(
        self, node_id: str, dag: PlanDAG, state: AgentState
    ) -> str:
        """Build context from resolved dependency nodes."""
        deps = dag.get_dependencies(node_id)
        context_parts = []
        for dep_id in deps:
            dep_state = state.nodes.get(dep_id)
            if dep_state and dep_state.status == NodeStatus.RESOLVED and dep_state.answer:
                context_parts.append(
                    f"[{dep_id}] {dep_state.question}\n"
                    f"Answer: {dep_state.answer[:500]}"
                )
        return "\n\n".join(context_parts)

    # ─── Logging / Display Methods ────────────────────────────

    def _log_header(self, query: str) -> None:
        if not self.verbose:
            return
        console.print()
        console.print(Panel(
            f"[bold white]{query}[/bold white]",
            title="[bold cyan]SAGE Research Agent[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    def _log_phase(self, phase: str, message: str) -> None:
        if not self.verbose:
            return
        colors = {
            "PLANNING": "yellow",
            "EXECUTION": "green",
            "COMPLETE": "bold green",
        }
        color = colors.get(phase, "white")
        console.print(f"\n[{color}]━━━ {phase}: {message} ━━━[/{color}]")

    def _log_dag(self, dag: PlanDAG) -> None:
        if not self.verbose:
            return
        table = Table(
            title="Sub-Goal DAG",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold yellow",
        )
        table.add_column("ID", style="cyan", width=12)
        table.add_column("Question", style="white")
        table.add_column("Deps", style="dim", width=15)
        table.add_column("Depth", justify="center", width=6)

        for nid in dag.topological_sort():
            node = dag.get_node(nid)
            deps = dag.get_dependencies(nid)
            dep_str = ", ".join(deps) if deps else "—"
            table.add_row(nid, node.question, dep_str, str(node.depth))

        console.print(table)

    def _log_node_start(self, node_id: str, question: str, iteration: int) -> None:
        if not self.verbose:
            return
        console.print(
            f"\n[bold blue]▶ Iteration {iteration} | "
            f"Node: {node_id}[/bold blue]"
        )
        console.print(f"  [dim]Question: {question}[/dim]")

    def _log_react_step(self, step: int, thought: str, action: str) -> None:
        if not self.verbose:
            return
        console.print(f"  [yellow]Step {step}[/yellow]")
        console.print(f"    💭 Thought: {thought[:150]}")
        console.print(f"    🔧 Action: [cyan]{action}[/cyan]")

    def _log_react_finish(self, answer: str) -> None:
        if not self.verbose:
            return
        console.print(f"    ✅ Answer: {answer[:200]}")

    def _log_tool_result(self, tool_name: str, success: bool) -> None:
        if not self.verbose:
            return
        icon = "✓" if success else "✗"
        color = "green" if success else "red"
        console.print(f"    [{color}]{icon} {tool_name} completed[/{color}]")

    def _log_critic_start(self, node_id: str) -> None:
        if not self.verbose:
            return
        console.print(f"  [magenta]🔍 Evidence Critic evaluating {node_id}...[/magenta]")

    def _log_critic_result(self, verdict) -> None:
        if not self.verbose:
            return
        console.print(
            f"    Confidence: {verdict.confidence:.2f} | "
            f"Signal: [bold]{verdict.signal}[/bold]"
        )
        if verdict.contradictions:
            console.print(f"    ⚠ Contradictions: {verdict.contradictions}")

    def _log_signal(self, signal: str, node_id: str, confidence: float) -> None:
        if not self.verbose:
            return
        colors = {"ACCEPT": "green", "RETRY": "yellow", "ESCALATE": "red"}
        color = colors.get(signal, "white")
        console.print(
            f"  [{color}]→ {signal}[/{color}] {node_id} "
            f"(confidence: {confidence:.2f})"
        )

    def _log_replan_node(self, node_id: str, question: str) -> None:
        if not self.verbose:
            return
        console.print(
            f"  [red]+ Re-plan node: {node_id}[/red] — {question}"
        )

    def _log_warning(self, message: str) -> None:
        if not self.verbose:
            return
        console.print(f"  [bold yellow]⚠ {message}[/bold yellow]")

    def _log_summary(self, state: AgentState) -> None:
        if not self.verbose:
            return
        summary = state.summary()
        console.print()

        table = Table(
            title="Agent Run Summary",
            box=box.ROUNDED,
            title_style="bold cyan",
        )
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Total Nodes", str(summary["total_nodes"]))
        table.add_row("Resolved", str(summary["resolved"]))
        table.add_row("Pending/Failed", str(summary["pending"]))
        table.add_row("LLM Calls", str(summary["total_llm_calls"]))
        table.add_row("Tool Calls", str(summary["total_tool_calls"]))
        table.add_row("Iterations", str(summary["iterations"]))
        table.add_row("Elapsed (s)", str(summary["elapsed_seconds"]))

        console.print(table)