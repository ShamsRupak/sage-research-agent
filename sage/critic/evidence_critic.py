"""
SAGE Evidence Critic — evaluates evidence quality and emits control signals.

After each sub-goal resolves, the Critic assesses the gathered evidence
via a structured LLM call. It returns:
  - confidence: float 0.0-1.0
  - contradictions: list of detected contradictions
  - signal: ACCEPT / RETRY / ESCALATE
  - rationale: explanation of the assessment

The signal drives the agent loop:
  ACCEPT  → mark node resolved, move on
  RETRY   → re-execute the same sub-goal with revised approach
  ESCALATE → trigger the re-planner to insert new sub-goals

This module is the key feedback mechanism that makes SAGE self-correcting.
"""

from __future__ import annotations

from sage.llm.prompts import CRITIC_SYSTEM, CRITIC_USER
from sage.llm.parser import parse_critic_response
from sage.memory.state import (
    AgentState,
    NodeState,
    NodeStatus,
    CriticVerdict,
)


class EvidenceCritic:
    """
    Evaluates evidence gathered for a sub-goal and emits a control signal.

    The Critic is a separate LLM call with a fixed JSON schema — it does
    not share context with the ReAct loop. This architectural separation
    ensures the evaluation is independent of the reasoning that produced
    the evidence.
    """

    def __init__(
        self,
        llm_client,
        confidence_threshold: float = 0.75,
    ) -> None:
        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold

    async def evaluate(
        self,
        node_state: NodeState,
        agent_state: AgentState,
    ) -> CriticVerdict:
        """
        Evaluate the evidence for a sub-goal node.

        Args:
            node_state: The node whose evidence we're evaluating
            agent_state: Global agent state for context

        Returns:
            CriticVerdict with confidence, contradictions, signal, and rationale
        """
        # Build evidence summary from the node's collected evidence
        evidence_text = self._format_evidence(node_state)
        tool_calls_text = self._format_tool_calls(node_state)

        # Build the critic prompt
        prompt = CRITIC_USER.format(
            question=node_state.question,
            evidence=evidence_text,
            tool_calls=tool_calls_text,
            retry_count=node_state.retry_count,
            max_retries=node_state.max_retries,
        )

        # Call LLM for evaluation
        raw_response = await self.llm_client.complete(
            prompt=prompt,
            system=CRITIC_SYSTEM,
            temperature=0.2,  # Low temperature for consistent evaluation
        )

        # Track the LLM call
        agent_state.record_llm_call()

        # Parse the response
        parsed = parse_critic_response(raw_response)

        # Apply overrides based on retry count
        parsed = self._apply_retry_logic(parsed, node_state)

        # Build the verdict
        verdict = CriticVerdict(
            confidence=parsed["confidence"],
            contradictions=parsed["contradictions"],
            signal=parsed["signal"],
            rationale=parsed["rationale"],
        )

        # Store the verdict on the node
        node_state.critic_verdicts.append(verdict)
        node_state.confidence = verdict.confidence

        return verdict

    def _apply_retry_logic(
        self, parsed: dict, node_state: NodeState
    ) -> dict:
        """
        Apply deterministic overrides to the LLM's assessment.

        Rules:
        - If max retries exceeded and signal is RETRY → escalate instead
        - If confidence >= threshold → always ACCEPT regardless of LLM signal
        - If confidence >= threshold but contradictions exist → still ACCEPT
          but keep contradictions noted
        """
        confidence = parsed["confidence"]
        signal = parsed["signal"]

        # Rule 1: If we've exhausted retries, escalate instead of retrying
        if signal == "RETRY" and node_state.retry_count >= node_state.max_retries:
            parsed["signal"] = "ESCALATE"
            parsed["rationale"] += (
                f" [Override: max retries ({node_state.max_retries}) exhausted, "
                f"escalating to re-planner]"
            )

        # Rule 2: High confidence always accepts
        elif confidence >= self.confidence_threshold and signal != "ACCEPT":
            parsed["signal"] = "ACCEPT"
            parsed["rationale"] += (
                f" [Override: confidence {confidence:.2f} >= threshold "
                f"{self.confidence_threshold}, accepting]"
            )

        # Rule 3: Very low confidence with no retries left → escalate
        elif confidence < 0.3 and node_state.retry_count >= node_state.max_retries:
            parsed["signal"] = "ESCALATE"
            parsed["rationale"] += (
                " [Override: very low confidence with no retries remaining, escalating]"
            )

        return parsed

    def _format_evidence(self, node_state: NodeState) -> str:
        """Format the node's evidence into a readable string for the Critic."""
        if not node_state.evidence:
            return "(No evidence gathered)"

        lines = []
        for i, ev in enumerate(node_state.evidence, 1):
            # Truncate individual evidence pieces to keep prompt manageable
            truncated = ev[:1000] + "..." if len(ev) > 1000 else ev
            lines.append(f"[Evidence {i}]\n{truncated}")

        return "\n\n".join(lines)

    def _format_tool_calls(self, node_state: NodeState) -> str:
        """Format the node's tool call history for the Critic."""
        if not node_state.tool_calls:
            return "(No tool calls made)"

        lines = []
        for tc in node_state.tool_calls:
            result_preview = str(tc.result.get("content", ""))[:200]
            lines.append(
                f"- {tc.tool_name}({tc.tool_input}) → "
                f"{'success' if tc.result.get('success') else 'failed'}: "
                f"{result_preview}"
            )

        return "\n".join(lines)


def apply_verdict(
    verdict: CriticVerdict,
    node_state: NodeState,
    agent_state: AgentState,
) -> str:
    """
    Apply a CriticVerdict to the agent state. Returns the signal for the agent loop.

    ACCEPT  → mark node as resolved
    RETRY   → increment retry counter, keep node in progress
    ESCALATE → mark node as escalated (re-planner will handle)
    """
    signal = verdict.signal

    if signal == "ACCEPT":
        node_state.status = NodeStatus.RESOLVED
        node_state.confidence = verdict.confidence

    elif signal == "RETRY":
        node_state.retry_count += 1
        node_state.status = NodeStatus.PENDING  # Re-queue for execution

    elif signal == "ESCALATE":
        node_state.status = NodeStatus.ESCALATED

    else:
        # Unknown signal — treat as retry
        node_state.retry_count += 1
        node_state.status = NodeStatus.PENDING

    return signal