# SAGE — Self-Adaptive Goal-directed Executor

**A multi-tool LLM agent with hierarchical planning and evidence-guided reasoning for automated research synthesis.**

Built from scratch in Python — no LangChain, no AutoGPT, no agent frameworks. All planning logic is deterministic code external to the LLM.

---

## Overview

SAGE takes a complex, open-ended research question and autonomously produces a structured, citation-aware analytical report. It does this through a five-stage pipeline:

1. **Decompose** — A deterministic Python planner breaks the query into a DAG (Directed Acyclic Graph) of 3–6 sub-goals with explicit dependencies
2. **Execute** — Each sub-goal runs through a ReAct-style loop, calling real tools (web search, URL fetching, claim extraction, code execution, cross-referencing)
3. **Evaluate** — An independent Evidence Critic scores confidence, detects contradictions, and emits control signals: `ACCEPT`, `RETRY`, or `ESCALATE`
4. **Adapt** — When evidence is insufficient, the re-planner inserts new sub-goals into the DAG mid-execution without discarding prior work
5. **Synthesize** — Findings are aggregated in topological (dependency) order into a Markdown report with per-claim provenance

The core design principle: **the LLM reasons, but the agent decides.** The LLM proposes tool calls and generates answers within individual sub-goals. The planner determines what sub-goals exist, in what order they execute, when to retry, and when to re-plan. This separation is what makes SAGE transparent, auditable, and empirically testable.

---

## Architecture

```
                    ┌─────────────────────────────┐
                    │         User Query           │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
  ┌─────────────────────────────────────────────────────────┐
  │              Hierarchical Planner  [Agent Layer]        │
  │  DAG decomposition · priority scheduling · re-planning  │
  │              (deterministic Python — no LLM)            │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │            LLM Reasoning Engine  [Neural Layer]         │
  │     ReAct loop: Thought → Action → Observation          │
  │          (per sub-goal, max 5 steps)                    │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │            Tool Execution Layer  [Execution Layer]      │
  │  web_search · fetch_url · extract_claims · code_run     │
  │                  cross_reference                        │
  └──────────────────────────┬──────────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │            Evidence Critic  [Control Layer]             │
  │  Confidence scoring · contradiction detection           │
  │     → ACCEPT / RETRY / ESCALATE                         │
  │  (deterministic overrides enforce termination)     ─────┼──→ Re-plan
  └──────────────────────────┬──────────────────────────────┘     (feedback)
                             │
                             ▼
  ┌─────────────────────────────────────────────────────────┐
  │            Synthesis & Report  [Output Layer]           │
  │  Topological DAG traversal → structured Markdown        │
  │  with citations, confidence table, and provenance       │
  └─────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Planning external to LLM** | Makes decisions auditable, testable via ablation, and prevents the LLM from derailing the investigation strategy |
| **DAG over linear plan** | Supports parallel sub-goals and explicit dependencies — sub-goal B waits for sub-goal A only if it actually needs A's answer |
| **Separate Evidence Critic** | Independent LLM call with fixed JSON schema prevents the reasoning engine from grading its own work |
| **Deterministic overrides on Critic** | Guarantees termination: max retries → escalate, high confidence → accept, regardless of LLM output |
| **No agent frameworks** | Built from scratch to demonstrate full understanding of every component (course requirement) |

---

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| LLM | Groq API (`llama-3.3-70b-versatile`) | Fast inference, free tier, 14,400 req/day |
| Fallback LLM | Google Gemini 1.5 Flash | Automatic failover if Groq rate-limits |
| Web Search | Tavily API | Agent-optimized — returns clean snippets, not raw HTML |
| URL Fetching | `httpx` + BeautifulSoup4 | Async HTTP with HTML-to-text extraction |
| Code Sandbox | `subprocess` + timeout | Safe execution of agent-generated Python snippets |
| State | `dataclasses` + `heapq` | Pure Python, no external dependencies |
| Output | `rich` | Beautiful terminal display for demo |
| Tests | `pytest` | 59 unit tests across 4 test files |

---

## Project Structure

```
sage-research-agent/
├── sage/                      # Core agent package
│   ├── agent.py               # Main orchestrator — wires all layers together
│   ├── planner/               # Hierarchical planning (4 modules)
│   │   ├── dag.py             #   DAG data structure with cycle detection
│   │   ├── decomposer.py      #   Query → sub-goals (LLM proposes, planner validates)
│   │   ├── scheduler.py       #   Min-heap priority queue with dependency gating
│   │   └── replanner.py       #   Inserts new sub-goals on ESCALATE signals
│   ├── tools/                 # Tool layer (6 modules)
│   │   ├── registry.py        #   Tool registration, dispatch, and description generation
│   │   ├── web_search.py      #   Tavily API integration
│   │   ├── fetch_url.py       #   HTTP fetch + HTML parsing
│   │   ├── extract_claims.py  #   LLM-powered claim extraction
│   │   ├── code_runner.py     #   Sandboxed Python execution
│   │   └── cross_reference.py #   Internal consistency checking
│   ├── llm/                   # LLM interface (3 modules)
│   │   ├── client.py          #   Provider-agnostic client with retry + fallback
│   │   ├── prompts.py         #   All prompt templates (centralized)
│   │   └── parser.py          #   Lenient JSON/ReAct output parsing
│   ├── critic/
│   │   └── evidence_critic.py #   Confidence scoring + control signals
│   ├── memory/
│   │   └── state.py           #   Shared state, reasoning traces, provenance
│   └── synthesis/
│       └── synthesizer.py     #   Topological synthesis + report generation
├── eval/                      # Evaluation framework
│   ├── queries.py             #   5 diverse test queries
│   ├── rubric.py              #   Metrics extraction and comparison tables
│   └── ablation.py            #   3-condition ablation runner
├── demo/
│   └── run_demo.py            #   End-to-end demo with rich terminal output
├── report/
│   ├── main.tex               #   Final LaTeX report
│   └── proposal.tex           #   Project proposal
└── tests/                     #   59 unit tests
    ├── test_dag.py
    ├── test_planner.py
    ├── test_critic.py
    └── test_tools.py
```

---

## Quick Start

```bash
# Clone and setup
git clone https://github.com/ShamsRupak/sage-research-agent.git
cd sage-research-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your Groq and Tavily keys:
#   GROQ_API_KEY=your_key    (https://console.groq.com/keys)
#   TAVILY_API_KEY=your_key  (https://app.tavily.com/home)

# Run tests
python -m pytest tests/ -v

# Run the demo
python -m demo.run_demo

# Run with a custom query
python -m demo.run_demo "Your research question here"

# Run the ablation study
python -m eval.ablation --query q1
```

---

## Demo Output (Abbreviated)

```
━━━ PLANNING: Decomposing query into sub-goals... ━━━

              Sub-Goal DAG
╭──────────┬──────────────────────────────────────┬───────────╮
│ ID       │ Question                             │ Depth     │
├──────────┼──────────────────────────────────────┼───────────┤
│ sub_1    │ Key architectural differences        │   0       │
│ sub_2    │ Performance on long-context tasks     │   1       │
│ sub_3    │ Computational efficiency trade-offs   │   1       │
│ sub_4    │ Empirical evidence                   │   2       │
│ sub_5    │ Open research questions              │   3       │
╰──────────┴──────────────────────────────────────┴───────────╯

━━━ EXECUTION: Starting agent loop... ━━━

▶ Iteration 1 | Node: sub_1
  💭 Thought: To answer this, I need to understand the fundamental differences...
  🔧 Action: web_search → ✓ 5 results
  🔧 Action: fetch_url → ✗ failed (403)
  🔧 Action: extract_claims → ✓ 6 claims
  🔍 Critic: confidence=0.80, signal=ACCEPT

▶ Iteration 2 | Node: sub_3
  🔧 Action: web_search → ✓
  🔧 Action: extract_claims → ✓ 8 claims
  🔧 Action: cross_reference → ✓ all consistent
  🔧 Action: finish
  🔍 Critic: confidence=0.85, signal=ACCEPT

...

━━━ COMPLETE: All sub-goals resolved! ━━━

     Agent Run Summary
╭────────────────┬────────╮
│ Total Nodes    │      5 │
│ Resolved       │      5 │
│ LLM Calls      │     28 │
│ Tool Calls     │     19 │
│ Elapsed (s)    │ 135.11 │
╰────────────────┴────────╯
```

---

## Ablation Study

SAGE includes a built-in ablation framework comparing three conditions:

| Condition | Description | Planner | Tools | Critic |
|-----------|-------------|---------|-------|--------|
| **Full SAGE** | Complete pipeline | ✓ DAG | ✓ 5 tools | ✓ Confidence + signals |
| **Flat ReAct** | Single-node ReAct loop | ✗ | ✓ 3 tools | ✗ |
| **Single LLM** | One prompt, one response | ✗ | ✗ | ✗ |

Results on the transformer vs. RNN query (actual measured run):

| Metric | SAGE | Flat ReAct | Single LLM |
|--------|------|------------|------------|
| Sub-goals | 5 | 1 | 1 |
| LLM Calls | 28 | 8 | 1 |
| Tool Calls | 19 | 5 | 0 |
| Avg Confidence | 0.82 | 0.50 (default) | 0.00 |
| Citations | 14 | 3 | 0 |
| Time (s) | 135 | 42 | 3 |

---

## Development Progress

- [x] Phase 0: Repository and environment setup
- [x] Phase 1: Core data structures (DAG, shared state) — 17 tests
- [x] Phase 2: Hierarchical planner (decomposer, scheduler, replanner) — 18 tests
- [x] Phase 3: LLM client with provider fallback and prompt templates
- [x] Phase 4: Tool layer (5 tools + registry) — 13 tests
- [x] Phase 5: Evidence Critic with deterministic overrides — 11 tests
- [x] Phase 6: Main agent loop orchestrator
- [x] Phase 7: Topological synthesis with provenance
- [x] Phase 8: End-to-end demo with rich terminal output
- [x] Phase 9: Evaluation framework and ablation study
- [x] Phase 10: Final LaTeX report

**59 tests passing** · **16 modules** · **13 commits**

---

## Team

| Member | Responsibilities |
|--------|-----------------|
| **Shams Rupak** | Hierarchical Planner (DAG, decomposer, scheduler, re-planner), priority scheduling algorithm, ablation study design, evaluation framework, final report |
| **Gagan Sapkota** | Tool layer (5 tools + registry), Evidence Critic module, state/memory management, synthesis pipeline, demo interface |

---

*ESE 561 — Artificial Intelligence · Stony Brook University · Spring 2026*
