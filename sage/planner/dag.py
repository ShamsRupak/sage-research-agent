"""
SAGE DAG — Directed Acyclic Graph for sub-goal management.

The DAG is the core planning data structure. Each node represents an atomic
sub-question. Edges encode dependencies (node B depends on node A means A
must be resolved before B can execute). The planner builds this DAG during
query decomposition and traverses it during execution.

All graph logic is deterministic Python — no LLM involvement.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class DAGNode:
    """
    A single node in the planning DAG.

    Attributes:
        node_id: Unique identifier (e.g., "sub_1", "sub_2")
        question: The sub-question this node answers
        dependencies: IDs of nodes that must resolve before this one
        priority: Lower is higher priority (used by the scheduler)
        depth: Distance from root in the DAG (0 = no dependencies)
        metadata: Optional extra info (e.g., decomposition rationale)
    """
    node_id: str
    question: str
    dependencies: list[str] = field(default_factory=list)
    priority: float = 0.0
    depth: int = 0
    metadata: dict = field(default_factory=dict)


class PlanDAG:
    """
    Directed Acyclic Graph for managing sub-goal decomposition.

    Provides methods for adding nodes and edges, checking dependencies,
    topological sorting, and querying the ready frontier (nodes whose
    dependencies are all resolved).
    """

    def __init__(self) -> None:
        self._nodes: dict[str, DAGNode] = {}
        self._edges: dict[str, list[str]] = {}        # parent -> [children]
        self._reverse_edges: dict[str, list[str]] = {} # child -> [parents]

    @property
    def nodes(self) -> dict[str, DAGNode]:
        return self._nodes

    def add_node(self, node: DAGNode) -> None:
        """Add a node to the DAG. Raises ValueError if ID already exists."""
        if node.node_id in self._nodes:
            raise ValueError(f"Node '{node.node_id}' already exists in DAG")
        self._nodes[node.node_id] = node
        if node.node_id not in self._edges:
            self._edges[node.node_id] = []
        if node.node_id not in self._reverse_edges:
            self._reverse_edges[node.node_id] = []

    def add_edge(self, parent_id: str, child_id: str) -> None:
        """
        Add a dependency edge: child depends on parent.
        Parent must be resolved before child can execute.
        Raises ValueError if either node doesn't exist or edge creates a cycle.
        """
        if parent_id not in self._nodes:
            raise ValueError(f"Parent node '{parent_id}' not in DAG")
        if child_id not in self._nodes:
            raise ValueError(f"Child node '{child_id}' not in DAG")
        if parent_id == child_id:
            raise ValueError("Self-loops are not allowed")

        # Add the edge
        if child_id not in self._edges[parent_id]:
            self._edges[parent_id].append(child_id)
        if parent_id not in self._reverse_edges[child_id]:
            self._reverse_edges[child_id].append(parent_id)

        # Update the child's dependencies list
        child_node = self._nodes[child_id]
        if parent_id not in child_node.dependencies:
            child_node.dependencies.append(parent_id)

        # Validate no cycle was introduced
        if self._has_cycle():
            # Roll back the edge
            self._edges[parent_id].remove(child_id)
            self._reverse_edges[child_id].remove(parent_id)
            child_node.dependencies.remove(parent_id)
            raise ValueError(
                f"Edge {parent_id} -> {child_id} would create a cycle"
            )

        # Update depth
        self._recompute_depths()

    def get_node(self, node_id: str) -> DAGNode:
        """Get a node by ID. Raises KeyError if not found."""
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found in DAG")
        return self._nodes[node_id]

    def get_dependencies(self, node_id: str) -> list[str]:
        """Return the list of node IDs that this node depends on."""
        return list(self._reverse_edges.get(node_id, []))

    def get_dependents(self, node_id: str) -> list[str]:
        """Return the list of node IDs that depend on this node."""
        return list(self._edges.get(node_id, []))

    def get_ready_nodes(self, resolved_ids: set[str]) -> list[DAGNode]:
        """
        Return nodes whose dependencies are ALL in resolved_ids
        and that are not themselves resolved.
        This is the 'frontier' — nodes eligible for execution.
        """
        ready = []
        for node_id, node in self._nodes.items():
            if node_id in resolved_ids:
                continue
            deps = self.get_dependencies(node_id)
            if all(d in resolved_ids for d in deps):
                ready.append(node)
        return ready

    def topological_sort(self) -> list[str]:
        """
        Return node IDs in topological order (Kahn's algorithm).
        Raises ValueError if the graph contains a cycle.
        """
        in_degree: dict[str, int] = {
            nid: len(self._reverse_edges.get(nid, []))
            for nid in self._nodes
        }
        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result: list[str] = []

        while queue:
            nid = queue.popleft()
            result.append(nid)
            for child in self._edges.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(result) != len(self._nodes):
            raise ValueError("DAG contains a cycle — topological sort failed")
        return result

    def size(self) -> int:
        """Return the number of nodes in the DAG."""
        return len(self._nodes)

    def _has_cycle(self) -> bool:
        """Check for cycles using topological sort."""
        try:
            self.topological_sort()
            return False
        except ValueError:
            return True

    def _recompute_depths(self) -> None:
        """Recompute depth for all nodes based on current edges."""
        for nid in self.topological_sort():
            deps = self.get_dependencies(nid)
            if not deps:
                self._nodes[nid].depth = 0
            else:
                self._nodes[nid].depth = (
                    max(self._nodes[d].depth for d in deps) + 1
                )

    def __repr__(self) -> str:
        lines = [f"PlanDAG({self.size()} nodes):"]
        for nid in self.topological_sort():
            node = self._nodes[nid]
            deps = self.get_dependencies(nid)
            dep_str = f" (depends on: {deps})" if deps else ""
            lines.append(
                f"  [{nid}] depth={node.depth} pri={node.priority:.2f} "
                f"| {node.question}{dep_str}"
            )
        return "\n".join(lines)