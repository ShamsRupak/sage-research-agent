"""Tests for the planner modules: decomposer, scheduler, replanner."""

import pytest
from sage.planner.dag import DAGNode, PlanDAG
from sage.planner.decomposer import (
    detect_complexity,
    parse_decomposition_response,
    validate_dependencies,
    build_dag_from_decomposition,
)
from sage.planner.scheduler import Scheduler, SchedulerEntry
from sage.planner.replanner import generate_replan_node_id
from sage.memory.state import AgentState, NodeStatus


# ─── Decomposer Tests ────────────────────────────────────────

class TestDetectComplexity:

    def test_simple_query(self):
        score = detect_complexity("What is photosynthesis?")
        assert score >= 1

    def test_comparative_query(self):
        score = detect_complexity(
            "Compare transformers and RNNs for long-context reasoning"
        )
        assert score >= 2

    def test_complex_query(self):
        score = detect_complexity(
            "Analyze the trade-offs between transformer-based and recurrent "
            "architectures for long-context reasoning, citing empirical evidence "
            "and identifying open research questions in the field"
        )
        assert score >= 3


class TestParseDecomposition:

    def test_valid_json(self):
        response = '''
        {
          "sub_questions": [
            {"id": "sub_1", "question": "What is X?", "depends_on": []},
            {"id": "sub_2", "question": "What is Y?", "depends_on": ["sub_1"]}
          ]
        }
        '''
        result = parse_decomposition_response(response)
        assert len(result) == 2
        assert result[0]["id"] == "sub_1"
        assert result[1]["depends_on"] == ["sub_1"]

    def test_markdown_fences(self):
        response = '```json\n{"sub_questions": [{"id": "s1", "question": "Q", "depends_on": []}]}\n```'
        result = parse_decomposition_response(response)
        assert len(result) == 1

    def test_trailing_comma(self):
        response = '{"sub_questions": [{"id": "s1", "question": "Q", "depends_on": [],},]}'
        result = parse_decomposition_response(response)
        assert len(result) == 1

    def test_invalid_json_returns_empty(self):
        result = parse_decomposition_response("This is not JSON at all")
        assert result == []

    def test_missing_required_fields(self):
        response = '{"sub_questions": [{"id": "s1"}]}'
        result = parse_decomposition_response(response)
        assert result == []


class TestValidateDependencies:

    def test_removes_invalid_deps(self):
        sqs = [
            {"id": "s1", "question": "Q1", "depends_on": ["s999"]},
            {"id": "s2", "question": "Q2", "depends_on": ["s1"]},
        ]
        validated = validate_dependencies(sqs)
        assert validated[0]["depends_on"] == []
        assert validated[1]["depends_on"] == ["s1"]


class TestBuildDAG:

    def test_builds_correct_dag(self):
        sqs = [
            {"id": "s1", "question": "Q1", "depends_on": []},
            {"id": "s2", "question": "Q2", "depends_on": []},
            {"id": "s3", "question": "Q3", "depends_on": ["s1", "s2"]},
        ]
        dag = build_dag_from_decomposition("Root?", sqs)
        assert dag.size() == 3
        assert set(dag.get_dependencies("s3")) == {"s1", "s2"}

    def test_skips_cyclic_edges(self):
        sqs = [
            {"id": "s1", "question": "Q1", "depends_on": ["s2"]},
            {"id": "s2", "question": "Q2", "depends_on": ["s1"]},
        ]
        dag = build_dag_from_decomposition("Root?", sqs)
        # One edge will succeed, the other will be skipped to prevent cycle
        assert dag.size() == 2


# ─── Scheduler Tests ──────────────────────────────────────────

class TestScheduler:

    def _make_dag_and_state(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="a", question="A"))
        dag.add_node(DAGNode(node_id="b", question="B"))
        dag.add_node(DAGNode(node_id="c", question="C"))
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")

        state = AgentState(root_query="Test")
        state.register_node("a", "A")
        state.register_node("b", "B")
        state.register_node("c", "C")
        return dag, state

    def test_initial_scheduling(self):
        dag, state = self._make_dag_and_state()
        scheduler = Scheduler(dag, state)
        scheduler.initialize()
        # 'a' has no deps, should be first
        next_id = scheduler.get_next()
        assert next_id == "a"

    def test_dependency_gating(self):
        dag, state = self._make_dag_and_state()
        scheduler = Scheduler(dag, state)
        scheduler.initialize()

        # Before resolving 'a', b and c should not be returned
        # Pop 'a' first
        scheduler.get_next()  # returns 'a'

        # b and c still blocked because 'a' not resolved
        next_id = scheduler.get_next()
        assert next_id is None

    def test_after_resolving_dependency(self):
        dag, state = self._make_dag_and_state()
        scheduler = Scheduler(dag, state)
        scheduler.initialize()

        scheduler.get_next()  # pops 'a'
        state.get_node("a").status = NodeStatus.RESOLVED

        # Now b or c should be available
        next_id = scheduler.get_next()
        assert next_id in ("b", "c")

    def test_has_pending(self):
        dag, state = self._make_dag_and_state()
        scheduler = Scheduler(dag, state)
        scheduler.initialize()
        assert scheduler.has_pending()

        # Resolve all
        for nid in ("a", "b", "c"):
            state.get_node(nid).status = NodeStatus.RESOLVED
        assert not scheduler.has_pending()

    def test_reprioritize(self):
        dag, state = self._make_dag_and_state()
        scheduler = Scheduler(dag, state)
        scheduler.initialize()
        # This should not raise
        scheduler.reprioritize("a", 0.01)


# ─── Replanner Tests ─────────────────────────────────────────

class TestReplanHelpers:

    def test_generate_unique_id(self):
        dag = PlanDAG()
        dag.add_node(DAGNode(node_id="replan_1", question="Q"))
        new_id = generate_replan_node_id(dag)
        assert new_id == "replan_2"

    def test_generate_id_no_conflict(self):
        dag = PlanDAG()
        new_id = generate_replan_node_id(dag)
        assert new_id == "replan_1"