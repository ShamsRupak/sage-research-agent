"""Tests for the Evidence Critic module."""

import asyncio
import pytest
from sage.critic.evidence_critic import EvidenceCritic, apply_verdict
from sage.memory.state import (
    AgentState,
    NodeState,
    NodeStatus,
    CriticVerdict,
    ToolCall,
)


# ─── Mock LLM Client ─────────────────────────────────────────

class MockLLMClient:
    """Returns a predetermined JSON response for testing."""

    def __init__(self, response: str):
        self.response = response
        self.call_count = 0

    async def complete(self, prompt: str, system: str = "", temperature: float = 0.7, **kwargs) -> str:
        self.call_count += 1
        return self.response


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ─── Critic Evaluation Tests ────────────────────────────────

class TestEvidenceCritic:

    def _make_node_and_state(self, evidence=None, retry_count=0):
        state = AgentState(root_query="Test query")
        node = state.register_node("s1", "What is X?")
        node.evidence = evidence or ["Some evidence about X"]
        node.retry_count = retry_count
        node.tool_calls = [
            ToolCall(
                tool_name="web_search",
                tool_input={"query": "X"},
                result={"success": True, "content": "Found info about X"},
            )
        ]
        return node, state

    def test_accept_signal(self):
        mock_response = '''{
            "confidence": 0.85,
            "contradictions": [],
            "signal": "ACCEPT",
            "rationale": "Evidence is strong and consistent"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal == "ACCEPT"
        assert verdict.confidence == 0.85
        assert verdict.contradictions == []
        assert client.call_count == 1

    def test_retry_signal(self):
        mock_response = '''{
            "confidence": 0.5,
            "contradictions": [],
            "signal": "RETRY",
            "rationale": "Evidence is weak, needs more sources"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal == "RETRY"
        assert verdict.confidence == 0.5

    def test_escalate_signal(self):
        mock_response = '''{
            "confidence": 0.2,
            "contradictions": ["Source A says yes, Source B says no"],
            "signal": "ESCALATE",
            "rationale": "Fundamental contradiction in evidence"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal == "ESCALATE"
        assert len(verdict.contradictions) == 1

    def test_retry_override_when_max_retries_exceeded(self):
        """If LLM says RETRY but retries are exhausted, should escalate."""
        mock_response = '''{
            "confidence": 0.5,
            "contradictions": [],
            "signal": "RETRY",
            "rationale": "Needs more evidence"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state(retry_count=2)
        node.max_retries = 2

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal == "ESCALATE"
        assert "exhausted" in verdict.rationale.lower()

    def test_high_confidence_override_to_accept(self):
        """If confidence is above threshold, always accept."""
        mock_response = '''{
            "confidence": 0.9,
            "contradictions": [],
            "signal": "RETRY",
            "rationale": "LLM incorrectly said retry"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal == "ACCEPT"

    def test_malformed_response_defaults(self):
        """If LLM returns garbage, should get safe defaults."""
        client = MockLLMClient("This is not JSON at all")
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        verdict = run_async(critic.evaluate(node, state))
        assert verdict.signal in ("RETRY", "ESCALATE")
        assert verdict.confidence == 0.0

    def test_verdict_stored_on_node(self):
        mock_response = '''{
            "confidence": 0.8,
            "contradictions": [],
            "signal": "ACCEPT",
            "rationale": "Good"
        }'''
        client = MockLLMClient(mock_response)
        critic = EvidenceCritic(client)
        node, state = self._make_node_and_state()

        run_async(critic.evaluate(node, state))
        assert len(node.critic_verdicts) == 1
        assert node.confidence == 0.8


# ─── Apply Verdict Tests ────────────────────────────────────

class TestApplyVerdict:

    def test_accept_resolves_node(self):
        state = AgentState(root_query="Test")
        node = state.register_node("s1", "Q")
        verdict = CriticVerdict(
            confidence=0.85, contradictions=[], signal="ACCEPT", rationale="Good"
        )
        result = apply_verdict(verdict, node, state)
        assert result == "ACCEPT"
        assert node.status == NodeStatus.RESOLVED

    def test_retry_increments_counter(self):
        state = AgentState(root_query="Test")
        node = state.register_node("s1", "Q")
        original_count = node.retry_count
        verdict = CriticVerdict(
            confidence=0.5, contradictions=[], signal="RETRY", rationale="Weak"
        )
        apply_verdict(verdict, node, state)
        assert node.retry_count == original_count + 1
        assert node.status == NodeStatus.PENDING

    def test_escalate_marks_node(self):
        state = AgentState(root_query="Test")
        node = state.register_node("s1", "Q")
        verdict = CriticVerdict(
            confidence=0.2, contradictions=["conflict"], signal="ESCALATE", rationale="Bad"
        )
        apply_verdict(verdict, node, state)
        assert node.status == NodeStatus.ESCALATED

    def test_unknown_signal_treated_as_retry(self):
        state = AgentState(root_query="Test")
        node = state.register_node("s1", "Q")
        verdict = CriticVerdict(
            confidence=0.5, contradictions=[], signal="UNKNOWN", rationale="?"
        )
        apply_verdict(verdict, node, state)
        assert node.status == NodeStatus.PENDING
        assert node.retry_count == 1