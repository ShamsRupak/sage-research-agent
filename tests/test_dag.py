"""Tests for the DAG data structure and shared state."""

import pytest
from sage.planner.dag import DAGNode, PlanDAG
from sage.memory.state import AgentState, NodeStatus


# ─── PlanDAG Tests ────────────────────────────────────────────

class TestPlanDAG:

    def test_add_node(self):
        dag = PlanDAG()
        node = DAGNode(node_id="s1", question="What is X?")
        dag.add_node(node)
        assert dag.size() == 1
        assert dag.get_node("s1").question == "What is X?"

    def test_duplicate_node_raises(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="s1", question="Q1"))
        with pytest.raises(ValueError, match="already exists"):
            dag.add_node(DAGNode(node_id="s1", question="Q2"))

    def test_add_edge_and_dependencies(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="s1", question="Q1"))
        dag.add_node(DAGNode(node_id="s2", question="Q2"))
        dag.add_edge("s1", "s2")
        assert "s1" in dag.get_dependencies("s2")
        assert "s2" in dag.get_dependents("s1")

    def test_edge_missing_node_raises(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="s1", question="Q1"))
        with pytest.raises(ValueError, match="not in DAG"):
            dag.add_edge("s1", "s999")

    def test_self_loop_raises(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="s1", question="Q1"))
        with pytest.raises(ValueError, match="Self-loops"):
            dag.add_edge("s1", "s1")

    def test_cycle_detection(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="a", question="A"))
        dag.add_node(DAGNode(node_id="b", question="B"))
        dag.add_node(DAGNode(node_id="c", question="C"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        with pytest.raises(ValueError, match="cycle"):
            dag.add_edge("c", "a")

    def test_topological_sort_linear(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="a", question="A"))
        dag.add_node(DAGNode(node_id="b", question="B"))
        dag.add_node(DAGNode(node_id="c", question="C"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_topological_sort_diamond(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="root", question="Root"))
        dag.add_node(DAGNode(node_id="left", question="Left"))
        dag.add_node(DAGNode(node_id="right", question="Right"))
        dag.add_node(DAGNode(node_id="join", question="Join"))
        dag.add_edge("root", "left")
        dag.add_edge("root", "right")
        dag.add_edge("left", "join")
        dag.add_edge("right", "join")
        order = dag.topological_sort()
        assert order.index("root") < order.index("left")
        assert order.index("root") < order.index("right")
        assert order.index("left") < order.index("join")
        assert order.index("right") < order.index("join")

    def test_depth_computation(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="a", question="A"))
        dag.add_node(DAGNode(node_id="b", question="B"))
        dag.add_node(DAGNode(node_id="c", question="C"))
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        assert dag.get_node("a").depth == 0
        assert dag.get_node("b").depth == 1
        assert dag.get_node("c").depth == 2

    def test_get_ready_nodes(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="a", question="A"))
        dag.add_node(DAGNode(node_id="b", question="B"))
        dag.add_node(DAGNode(node_id="c", question="C"))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")

        # Initially only 'a' is ready (no deps)
        ready = dag.get_ready_nodes(resolved_ids=set())
        assert len(ready) == 1
        assert ready[0].node_id == "a"

        # After resolving 'a', both 'b' and 'c' are ready
        ready = dag.get_ready_nodes(resolved_ids={"a"})
        ready_ids = {n.node_id for n in ready}
        assert ready_ids == {"b", "c"}


# ─── AgentState Tests ─────────────────────────────────────────

class TestAgentState:

    def test_register_and_get_node(self):
        state = AgentState(root_query="Test query")
        state.register_node("s1", "Sub question 1")
        node = state.get_node("s1")
        assert node.question == "Sub question 1"
        assert node.status == NodeStatus.PENDING

    def test_duplicate_register_raises(self):
        state = AgentState(root_query="Test")
        state.register_node("s1", "Q1")
        with pytest.raises(ValueError, match="already exists"):
            state.register_node("s1", "Q2")

    def test_missing_node_raises(self):
        state = AgentState(root_query="Test")
        with pytest.raises(KeyError):
            state.get_node("nonexistent")

    def test_all_resolved(self):
        state = AgentState(root_query="Test")
        state.register_node("s1", "Q1")
        state.register_node("s2", "Q2")
        assert not state.all_resolved()

        state.get_node("s1").status = NodeStatus.RESOLVED
        assert not state.all_resolved()

        state.get_node("s2").status = NodeStatus.RESOLVED
        assert state.all_resolved()

    def test_failed_counts_as_done(self):
        state = AgentState(root_query="Test")
        state.register_node("s1", "Q1")
        state.get_node("s1").status = NodeStatus.FAILED
        assert state.all_resolved()

    def test_summary(self):
        state = AgentState(root_query="Big question")
        state.register_node("s1", "Q1")
        state.get_node("s1").status = NodeStatus.RESOLVED
        state.register_node("s2", "Q2")
        s = state.summary()
        assert s["total_nodes"] == 2
        assert s["resolved"] == 1
        assert s["pending"] == 1

    def test_record_llm_call(self):
        state = AgentState(root_query="Test")
        state.record_llm_call(tokens=150)
        state.record_llm_call(tokens=200)
        assert state.total_llm_calls == 2
        assert state.total_tokens_used == 350