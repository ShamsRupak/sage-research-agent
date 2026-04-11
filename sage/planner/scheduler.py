"""
SAGE Priority Scheduler — determines sub-goal execution order.

Uses a min-heap priority queue. Priority is computed from:
1. Dependency depth (nodes with no unresolved deps go first)
2. Relevance score (cosine similarity of sub-question to root query)
3. Confidence deficit (low-confidence nodes get re-prioritized)

All logic is deterministic Python — no LLM involvement.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Optional

from sage.planner.dag import PlanDAG, DAGNode
from sage.memory.state import AgentState, NodeStatus


@dataclass(order=True)
class SchedulerEntry:
    """
    A heap entry. Lower priority value = executed first.
    The node_id is stored but not used for comparison.
    """
    priority: float
    node_id: str = field(compare=False)


class Scheduler:
    """
    Dependency-aware priority scheduler for DAG nodes.

    Nodes are eligible for execution only when all their dependencies
    are resolved. Among eligible nodes, the one with the lowest priority
    score is selected next.
    """

    def __init__(
        self,
        dag: PlanDAG,
        state: AgentState,
        relevance_scorer: Optional[object] = None,
        depth_weight: float = 0.4,
        relevance_weight: float = 0.3,
        deficit_weight: float = 0.3,
    ) -> None:
        self.dag = dag
        self.state = state
        self.relevance_scorer = relevance_scorer
        self.depth_weight = depth_weight
        self.relevance_weight = relevance_weight
        self.deficit_weight = deficit_weight
        self._heap: list[SchedulerEntry] = []
        self._in_heap: set[str] = set()

    def compute_priority(
        self,
        node: DAGNode,
        relevance_score: float = 0.5,
    ) -> float:
        """
        Compute priority score for a node. Lower = higher priority.

        Components:
        - depth_score: normalized depth (0=root, 1=deepest)
        - relevance_score: 1 - cosine_similarity (so more relevant = lower)
        - deficit_score: 1 - confidence (so lower confidence = higher priority)
        """
        max_depth = max(
            (n.depth for n in self.dag.nodes.values()), default=1
        )
        max_depth = max(max_depth, 1)  # avoid division by zero
        depth_score = node.depth / max_depth

        # Invert relevance: higher similarity → lower priority value
        relevance_component = 1.0 - relevance_score

        # Confidence deficit: lower confidence → lower priority value (= run first)
        node_state = self.state.nodes.get(node.node_id)
        current_confidence = node_state.confidence if node_state else 0.0
        deficit_score = 1.0 - current_confidence

        priority = (
            self.depth_weight * depth_score
            + self.relevance_weight * relevance_component
            + self.deficit_weight * deficit_score
        )
        return priority

    def initialize(self, relevance_scores: dict[str, float] | None = None) -> None:
        """
        Populate the heap with all nodes, computing initial priorities.
        relevance_scores maps node_id -> similarity score (0 to 1).
        """
        if relevance_scores is None:
            relevance_scores = {}

        self._heap = []
        self._in_heap = set()

        for node_id, node in self.dag.nodes.items():
            rel_score = relevance_scores.get(node_id, 0.5)
            priority = self.compute_priority(node, rel_score)
            node.priority = priority
            heapq.heappush(self._heap, SchedulerEntry(priority, node_id))
            self._in_heap.add(node_id)

    def get_next(self) -> str | None:
        """
        Pop and return the highest-priority node that is ready to execute
        (all dependencies resolved). Returns None if no node is ready.
        """
        resolved = {
            nid for nid, ns in self.state.nodes.items()
            if ns.status in (NodeStatus.RESOLVED, NodeStatus.FAILED)
        }

        # Collect entries that aren't ready yet to re-push
        deferred: list[SchedulerEntry] = []
        result: str | None = None

        while self._heap:
            entry = heapq.heappop(self._heap)
            node_id = entry.node_id

            # Skip if already resolved
            if node_id in resolved:
                self._in_heap.discard(node_id)
                continue

            # Check if dependencies are met
            deps = self.dag.get_dependencies(node_id)
            if all(d in resolved for d in deps):
                result = node_id
                self._in_heap.discard(node_id)
                break
            else:
                deferred.append(entry)

        # Put deferred entries back
        for entry in deferred:
            heapq.heappush(self._heap, entry)

        return result

    def reprioritize(self, node_id: str, new_priority: float) -> None:
        """
        Update priority for a node (e.g., after a RETRY with low confidence).
        Removes old entry and pushes new one.
        """
        # Lazy deletion: just push a new entry with updated priority
        # Old entries for same node_id will be skipped in get_next if resolved
        self.dag.get_node(node_id).priority = new_priority
        heapq.heappush(self._heap, SchedulerEntry(new_priority, node_id))
        self._in_heap.add(node_id)

    def add_node(self, node_id: str, relevance_score: float = 0.5) -> None:
        """Add a newly inserted node (from re-planning) to the schedule."""
        node = self.dag.get_node(node_id)
        priority = self.compute_priority(node, relevance_score)
        node.priority = priority
        heapq.heappush(self._heap, SchedulerEntry(priority, node_id))
        self._in_heap.add(node_id)

    def has_pending(self) -> bool:
        """Check if there are any unresolved nodes left in the schedule."""
        resolved = {
            nid for nid, ns in self.state.nodes.items()
            if ns.status in (NodeStatus.RESOLVED, NodeStatus.FAILED)
        }
        return any(nid not in resolved for nid in self._in_heap)