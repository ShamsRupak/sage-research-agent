"""
SAGE Shared State — central data store passed through every stage of the agent loop.

Stores the DAG state, per-node evidence, reasoning traces, and provenance mapping.
All modules read from and write to this single state object, ensuring cross-step
coherence without requiring the LLM to re-derive prior findings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeStatus(Enum):
    """Lifecycle status of a DAG node."""
    PENDING = "pending"        # Not yet attempted
    IN_PROGRESS = "in_progress"  # Currently being executed
    RESOLVED = "resolved"      # Successfully completed with sufficient confidence
    FAILED = "failed"          # Failed after max retries
    ESCALATED = "escalated"    # Critic triggered re-planning


@dataclass
class ToolCall:
    """Record of a single tool invocation."""
    tool_name: str
    tool_input: dict[str, Any]
    result: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReasoningStep:
    """One step in the ReAct loop for a sub-goal."""
    thought: str
    action: str | None = None       # Tool name or "finish"
    action_input: dict[str, Any] | None = None
    observation: str | None = None   # Tool result or final answer
    timestamp: float = field(default_factory=time.time)


@dataclass
class CriticVerdict:
    """Output of the Evidence Critic for a sub-goal."""
    confidence: float              # 0.0 to 1.0
    contradictions: list[str]      # List of detected contradictions
    signal: str                    # "ACCEPT", "RETRY", or "ESCALATE"
    rationale: str                 # Critic's explanation
    timestamp: float = field(default_factory=time.time)


@dataclass
class ProvenanceRecord:
    """Links a claim to the tool call and source that produced it."""
    claim: str
    source_url: str | None = None
    tool_call: ToolCall | None = None
    node_id: str | None = None


@dataclass
class NodeState:
    """All state associated with a single DAG node (sub-goal)."""
    node_id: str
    question: str
    status: NodeStatus = NodeStatus.PENDING
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    reasoning_trace: list[ReasoningStep] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    critic_verdicts: list[CriticVerdict] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    answer: str | None = None
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class AgentState:
    """
    Top-level shared state for the entire SAGE agent run.

    This object is created once per query and threaded through every module:
    planner, LLM client, tool executor, critic, and synthesizer.
    """
    # The original user query
    root_query: str

    # Per-node state, keyed by node_id
    nodes: dict[str, NodeState] = field(default_factory=dict)

    # Global counters and config
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_tokens_used: int = 0
    max_iterations: int = 50
    confidence_threshold: float = 0.75
    iteration_count: int = 0

    # Timestamps
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    # Global provenance map
    all_provenance: list[ProvenanceRecord] = field(default_factory=list)

    def get_node(self, node_id: str) -> NodeState:
        """Retrieve a node's state by ID. Raises KeyError if not found."""
        if node_id not in self.nodes:
            raise KeyError(f"Node '{node_id}' not found in state")
        return self.nodes[node_id]

    def register_node(self, node_id: str, question: str) -> NodeState:
        """Create and register a new node in the state."""
        if node_id in self.nodes:
            raise ValueError(f"Node '{node_id}' already exists")
        node = NodeState(node_id=node_id, question=question)
        self.nodes[node_id] = node
        return node

    def all_resolved(self) -> bool:
        """Check if every node has met the confidence threshold or failed."""
        if not self.nodes:
            return False
        return all(
            n.status in (NodeStatus.RESOLVED, NodeStatus.FAILED)
            for n in self.nodes.values()
        )

    def resolved_nodes(self) -> list[NodeState]:
        """Return all nodes that have been successfully resolved."""
        return [n for n in self.nodes.values() if n.status == NodeStatus.RESOLVED]

    def pending_nodes(self) -> list[NodeState]:
        """Return all nodes still pending or in progress."""
        return [
            n for n in self.nodes.values()
            if n.status in (NodeStatus.PENDING, NodeStatus.IN_PROGRESS)
        ]

    def record_llm_call(self, tokens: int = 0) -> None:
        """Increment LLM call counter and token usage."""
        self.total_llm_calls += 1
        self.total_tokens_used += tokens

    def record_tool_call(self, node_id: str, tool_call: ToolCall) -> None:
        """Record a tool call on a specific node and globally."""
        self.total_tool_calls += 1
        node = self.get_node(node_id)
        node.tool_calls.append(tool_call)

    def finalize(self) -> None:
        """Mark the agent run as complete."""
        self.end_time = time.time()

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for logging/display."""
        elapsed = (self.end_time or time.time()) - self.start_time
        return {
            "root_query": self.root_query,
            "total_nodes": len(self.nodes),
            "resolved": len(self.resolved_nodes()),
            "pending": len(self.pending_nodes()),
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens_used,
            "iterations": self.iteration_count,
            "elapsed_seconds": round(elapsed, 2),
        }