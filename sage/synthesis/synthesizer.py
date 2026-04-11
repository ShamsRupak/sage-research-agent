"""
SAGE Synthesizer — produces the final research report.

Traverses the resolved DAG in topological order, aggregates evidence
and claims with provenance, and uses an LLM call to produce a
structured, citation-aware Markdown report.

The topological ordering ensures dependent findings are always
synthesized after their prerequisites — this is a structural
guarantee independent of LLM output quality.
"""

from __future__ import annotations

from sage.planner.dag import PlanDAG
from sage.memory.state import AgentState, NodeStatus
from sage.llm.client import LLMClient
from sage.llm.prompts import SYNTHESIS_SYSTEM, SYNTHESIS_USER


class Synthesizer:
    """
    Produces a structured research report from resolved DAG nodes.

    Usage:
        synth = Synthesizer(llm_client)
        report = await synth.synthesize(dag, state)
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def synthesize(
        self,
        dag: PlanDAG,
        state: AgentState,
    ) -> str:
        """
        Produce a Markdown research report from all resolved sub-goals.

        Steps:
        1. Topologically sort the DAG
        2. Collect findings from each resolved node in order
        3. Collect provenance data
        4. Call the LLM to synthesize into a coherent report
        5. Append a provenance appendix

        Returns the full report as a Markdown string.
        """
        # Step 1: Get topological order
        try:
            topo_order = dag.topological_sort()
        except ValueError:
            # Fallback: just use whatever order we have
            topo_order = list(dag.nodes.keys())

        # Step 2: Collect findings in dependency order
        findings = self._collect_findings(topo_order, state)

        # Step 3: Collect provenance
        provenance = self._collect_provenance(state)

        # Step 4: Call LLM for synthesis
        prompt = SYNTHESIS_USER.format(
            root_query=state.root_query,
            findings=findings,
            provenance=provenance,
        )

        raw_report = await self.llm_client.complete(
            prompt=prompt,
            system=SYNTHESIS_SYSTEM,
            temperature=0.4,
            max_tokens=4096,
        )
        state.record_llm_call()

        # Step 5: Assemble final report
        report = self._assemble_report(
            raw_report=raw_report,
            state=state,
            provenance=provenance,
        )

        return report

    def _collect_findings(
        self, topo_order: list[str], state: AgentState
    ) -> str:
        """
        Collect sub-goal findings in topological order.
        Only includes resolved nodes with answers.
        """
        sections = []
        for node_id in topo_order:
            node_state = state.nodes.get(node_id)
            if node_state is None:
                continue

            status_label = node_state.status.value
            answer = node_state.answer or "(No answer produced)"
            confidence = node_state.confidence

            # Truncate very long answers
            if len(answer) > 2000:
                answer = answer[:2000] + "\n[... truncated]"

            section = (
                f"### Sub-question [{node_id}]: {node_state.question}\n"
                f"Status: {status_label} | Confidence: {confidence:.2f}\n\n"
                f"{answer}\n"
            )
            sections.append(section)

        return "\n---\n".join(sections) if sections else "(No findings available)"

    def _collect_provenance(self, state: AgentState) -> str:
        """Collect provenance records as a formatted string."""
        if not state.all_provenance:
            return "(No provenance data)"

        lines = []
        seen_urls = set()
        for i, prov in enumerate(state.all_provenance, 1):
            url = prov.source_url or "unknown"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            claim_preview = prov.claim[:100] if prov.claim else "N/A"
            tool = prov.tool_call.tool_name if prov.tool_call else "N/A"
            node = prov.node_id or "N/A"

            lines.append(
                f"[{i}] Node: {node} | Tool: {tool}\n"
                f"    Source: {url}\n"
                f"    Claim: {claim_preview}"
            )

        return "\n".join(lines) if lines else "(No provenance data)"

    def _assemble_report(
        self,
        raw_report: str,
        state: AgentState,
        provenance: str,
    ) -> str:
        """
        Assemble the final Markdown report with header, body, and appendices.
        """
        summary = state.summary()

        header = (
            f"# Research Synthesis Report\n\n"
            f"**Query:** {state.root_query}\n\n"
            f"---\n\n"
        )

        metadata = (
            f"\n\n---\n\n"
            f"## Agent Execution Metadata\n\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Sub-goals | {summary['total_nodes']} |\n"
            f"| Resolved | {summary['resolved']} |\n"
            f"| LLM Calls | {summary['total_llm_calls']} |\n"
            f"| Tool Calls | {summary['total_tool_calls']} |\n"
            f"| Iterations | {summary['iterations']} |\n"
            f"| Elapsed (s) | {summary['elapsed_seconds']} |\n"
        )

        provenance_section = (
            f"\n\n---\n\n"
            f"## Source Provenance\n\n"
            f"```\n{provenance}\n```\n"
        )

        # Confidence breakdown
        confidence_section = self._build_confidence_section(state)

        return (
            header
            + raw_report
            + metadata
            + confidence_section
            + provenance_section
        )

    def _build_confidence_section(self, state: AgentState) -> str:
        """Build a per-sub-goal confidence summary."""
        lines = [
            "\n\n---\n\n",
            "## Sub-Goal Confidence Breakdown\n\n",
            "| Sub-Goal | Question | Confidence | Status |",
            "|----------|----------|------------|--------|",
        ]
        for node_id, node_state in state.nodes.items():
            question = node_state.question[:60]
            if len(node_state.question) > 60:
                question += "..."
            conf = f"{node_state.confidence:.2f}"
            status = node_state.status.value
            lines.append(f"| {node_id} | {question} | {conf} | {status} |")

        return "\n".join(lines) + "\n"


async def synthesize_report(
    dag: PlanDAG,
    state: AgentState,
    llm_client: LLMClient,
) -> str:
    """Convenience function for synthesizing a report."""
    synth = Synthesizer(llm_client)
    return await synth.synthesize(dag, state)