# SAGE — Self-Adaptive Goal-directed Executor

**A multi-tool LLM agent with hierarchical planning and evidence-guided reasoning for automated research synthesis.**

Built from scratch in Python — no LangChain, no AutoGPT, no agent frameworks. All planning logic is deterministic code external to the LLM.

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-59%20passing-brightgreen.svg)](#testing)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](#license)

---

## Audio & Visual Overview

🎧 [Listen to a 22-minute audio walkthrough of SAGE's architecture and design](media/How_SAGE_AI_Automates_Verifiable_Research.m4a) (generated via NotebookLM)

🎬 [Download the 7-minute video overview of SAGE's architecture and results](media/SageOverview.mp4) (generated via NotebookLM — click "Raw" or download to watch)

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
      ┌─────────────────┐
      │    User Query   │
      └────────┬────────┘
               ▼
  ┌──────────────────────────┐
  │   Hierarchical Planner   │  ◄──   DAG decomposition, priority scheduling,
  │  (Deterministic Python)  │        stopping conditions, re-planning
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  LLM Reasoning Engine    │  ◄──   ReAct loop: Thought → Action → Observation
  │  (per sub-goal, 5 steps) │        (per sub-goal, max 5 steps)
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  Tool Execution Layer    │  ◄──   web_search, fetch_url, extract_claims,
  │  (5 stateless tools)     │        code_run, cross_reference
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────┐
  │  Evidence Critic         │  ◄──   Confidence scoring, contradiction detection
  │  (separate LLM call)     │        → ACCEPT / RETRY / ESCALATE
  └────────────┬─────────────┘        (ESCALATE triggers re-planning ↑)
               ▼
  ┌──────────────────────────┐
  │  Synthesis & Report      │  ◄──   Topological DAG traversal → structured
  │  (dependency-ordered)    │        Markdown with citations + provenance
  └──────────────────────────┘
```

The full architectural diagram and design discussion are in [`report/main.tex`](report/main.tex).

---

## Tech Stack

| Component | Technology |
|---|---|
| Primary LLM | Groq API (`llama-3.3-70b-versatile`) |
| Fallback LLM | Google Gemini (`gemini-2.5-flash`) |
| Web search | Tavily API |
| URL fetcher | `httpx` + BeautifulSoup4 |
| Code sandbox | `subprocess` with timeout guard |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| State management | Pure Python (`dataclasses`, `heapq`) |
| Terminal UI | `rich` |
| Testing | `pytest` (59 tests) |

**No external agent frameworks are used** — no LangChain, LlamaIndex, AutoGPT, or similar. The entire agent structure is built from scratch.

---

## Project Structure

```
sage-research-agent/
├── sage/                      # Core agent package
│   ├── agent.py               # Main orchestrator
│   ├── planner/               # Hierarchical planning (4 modules)
│   │   ├── dag.py             #   DAG with cycle detection
│   │   ├── decomposer.py      #   Query → sub-goals
│   │   ├── scheduler.py       #   Priority queue + dependency gating
│   │   └── replanner.py       #   Insert nodes on ESCALATE
│   ├── tools/                 # Tool layer (6 modules)
│   │   ├── registry.py        #   Registration + dispatch
│   │   ├── web_search.py      #   Tavily API
│   │   ├── fetch_url.py       #   HTTP fetch + parsing
│   │   ├── extract_claims.py  #   LLM claim extraction
│   │   ├── code_runner.py     #   Sandboxed execution
│   │   └── cross_reference.py #   Consistency checking
│   ├── llm/                   # LLM interface (3 modules)
│   │   ├── client.py          #   Provider-agnostic + fallback
│   │   ├── prompts.py         #   All prompt templates
│   │   └── parser.py          #   Lenient JSON parsing
│   ├── critic/
│   │   └── evidence_critic.py #   Confidence + control signals
│   ├── memory/
│   │   └── state.py           #   Shared state + provenance
│   └── synthesis/
│       └── synthesizer.py     #   Topological synthesis
├── eval/                      # Evaluation framework
│   ├── queries.py             #   5 test queries
│   ├── rubric.py              #   Metrics + comparison
│   └── ablation.py            #   3-condition ablation
├── eval_outputs/              # Per-run reports + ablation_results.txt
├── demo/
│   └── run_demo.py            #   End-to-end demo
├── report/
│   ├── main.tex               #   Final report
│   └── proposal.tex           #   Proposal
├── media/                     #   NotebookLM audio/video (Git LFS)
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
# Edit .env with your keys:
#   GROQ_API_KEY=your_key       (https://console.groq.com/keys)
#   TAVILY_API_KEY=your_key     (https://app.tavily.com/home)
#   GEMINI_API_KEY=your_key     (https://aistudio.google.com/apikey)  [optional fallback]

# Run tests
python -m pytest tests/ -v

# Run the demo
python -m demo.run_demo

# Run with a custom query
python -m demo.run_demo "Your research question here"

# Run the full ablation study (5 queries × 3 conditions, ~20 minutes)
python -m eval.ablation

# Run a specific query or condition
python -m eval.ablation --query q1
python -m eval.ablation --condition sage
```

---

## Demo Output (Abbreviated)

```
━━━ PLANNING: Decomposing query into sub-goals... ━━━

              Sub-Goal DAG
╭──────────┬──────────────────────────────────────┬───────╮
│ ID       │ Question                             │ Depth │
├──────────┼──────────────────────────────────────┼───────┤
│ sub_1    │ Key architectural differences        │   0   │
│ sub_2    │ Performance on long-context tasks    │   1   │
│ sub_3    │ Computational efficiency trade-offs  │   1   │
│ sub_4    │ Empirical evidence                   │   2   │
│ sub_5    │ Open research questions              │   3   │
╰──────────┴──────────────────────────────────────┴───────╯

━━━ EXECUTION: Starting agent loop... ━━━

▶ Iteration 1 | Node: sub_1
  💭 Thought: I need to understand the fundamental differences...
  🔧 web_search → ✓ 5 results
  🔧 fetch_url → ✗ failed (403)
  🔧 extract_claims → ✓ 6 claims
  🔍 Critic: confidence=0.80, signal=ACCEPT

▶ Iteration 2 | Node: sub_3
  🔧 web_search → ✓
  🔧 extract_claims → ✓ 8 claims
  🔧 cross_reference → ✓ all consistent
  🔧 finish
  🔍 Critic: confidence=0.65, signal=RETRY

▶ Iteration 3 | Node: sub_3 (retry)
  🔧 web_search → ✓ refined query
  🔧 extract_claims → ✓ quantitative claims
  🔧 finish
  🔍 Critic: confidence=0.85, signal=ACCEPT

...

━━━ COMPLETE: All sub-goals resolved! ━━━

     Agent Run Summary
╭────────────────┬───────╮
│ Total Nodes    │     5 │
│ Resolved       │     5 │
│ LLM Calls      │    37 │
│ Tool Calls     │    24 │
│ Citations      │    63 │
│ Elapsed (s)    │  32.0 │
╰────────────────┴───────╯
```

---

## Ablation Study — Complete Results

SAGE includes a built-in ablation framework comparing three conditions across five queries:

| Condition | Description | Planner | Tools | Critic |
|-----------|-------------|---------|-------|--------|
| **Full SAGE** | Complete pipeline | ✓ DAG | ✓ 5 tools | ✓ Confidence + signals |
| **Flat ReAct** | Single-node ReAct loop | ✗ | ✓ 5 tools | ✗ |
| **Single LLM** | One prompt, one response | ✗ | ✗ | ✗ |

All 15 runs in the latest sweep completed successfully. Numbers below are from actual measured executions.

### Per-Query Results

| Query | Condition | Nodes | LLM | Tools | Conf | Retry | Re-plan | Cites | Length | Time |
|-------|-----------|------:|----:|------:|-----:|------:|--------:|------:|-------:|-----:|
| q1 | SAGE | 5 | 37 | 24 | 0.84 | 1 | 0 | **63** | 11,494 | 32.0s |
| q1 | Flat ReAct | 1 | 6 | 5 | 0.50 | 0 | 0 | 0 | 611 | 7.2s |
| q1 | Single LLM | 1 | 1 | 0 | 0.00 | 0 | 0 | 0 | 5,952 | 3.2s |
| q2 | SAGE | 5 | 31 | 20 | 0.84 | 0 | 0 | **46** | 10,219 | 27.4s |
| q2 | Flat ReAct | 1 | 5 | 4 | 0.50 | 0 | 0 | 0 | 473 | 6.1s |
| q2 | Single LLM | 1 | 1 | 0 | 0.00 | 0 | 0 | 0 | 6,338 | 3.9s |
| q3 | SAGE | 24 | 180 | 133 | 0.82 | 15 | 6 | **219** | 36,768 | 189.1s |
| q3 | Flat ReAct | 1 | 7 | 6 | 0.50 | 0 | 0 | 0 | 615 | 11.9s |
| q3 | Single LLM | 1 | 1 | 0 | 0.00 | 0 | 0 | 0 | 6,058 | 3.9s |
| q4 | SAGE | 6 | 35 | 22 | 0.84 | 0 | 0 | **64** | 12,869 | 30.7s |
| q4 | Flat ReAct | 1 | 5 | 4 | 0.50 | 0 | 0 | 0 | 723 | 5.5s |
| q4 | Single LLM | 1 | 1 | 0 | 0.00 | 0 | 0 | 0 | 7,778 | 4.5s |
| q5 | SAGE | 36 | 188 | 139 | 0.83 | 14 | 10 | **266** | 39,835 | 190.8s |
| q5 | Flat ReAct | 1 | 7 | 6 | 0.50 | 0 | 0 | 0 | 942 | 8.7s |
| q5 | Single LLM | 1 | 1 | 0 | 0.00 | 0 | 0 | 0 | 6,355 | 3.4s |

### Aggregate Summary

| Condition | Avg Conf | Avg Tool Calls | Avg Citations | Avg Report Length | Avg Time | Total Retries | Total Re-plans |
|-----------|---------:|---------------:|--------------:|------------------:|---------:|--------------:|---------------:|
| **SAGE** | **0.834** | **67.6** | **131.6** | **22,237 chars** | 94.0s | 30 | 16 |
| Flat ReAct | 0.500 | 5.0 | 0.0 | 673 chars | 7.9s | 0 | 0 |
| Single LLM | 0.000 | 0.0 | 0.0 | 6,496 chars | 3.7s | 0 | 0 |

### Key Findings

- **Tools improve grounding decisively.** SAGE produced **658 total citations** across 5 queries; both baselines produced **0 citations on every query**. Tool access alone is not sufficient — the planner's focused sub-questions are what make tools effective.
- **The Critic enables self-correction.** Retries triggered on q1 (1), q3 (15), and q5 (14); re-planning triggered on q3 (6) and q5 (10). Neither baseline has any self-correction capability.
- **Planning structures the investigation.** SAGE decomposed q1, q2, and q4 into focused 5–6 sub-goal DAGs, ensuring foundational concepts were resolved before comparative analysis.
- **Re-planning expansion is a behavioral mode worth understanding.** q3 and q5 expanded to 24 and 36 nodes respectively; both produced the highest citation counts in the study (219 and 266) but at substantial computational cost (180–188 LLM calls vs. 31–37 for the well-behaved runs). See the failure analysis in [`report/main.tex`](report/main.tex).
- **LLM-based agents are non-deterministic.** A prior run of the same ablation showed q3 producing 0 citations and q5 running cleanly with 6 nodes; this run reversed the pattern. Single-run evaluations of agent systems necessarily understate this variance.

---

## Final Report

The full LaTeX report is in [`report/main.tex`](report/main.tex). It includes the architecture diagram, planning component details, complete ablation results, a representative agent trace, failure analysis, and connection to all four ESE 561 course modules.

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

**59 tests passing** · **16 modules** · **5 queries evaluated** · **15 ablation runs completed**

---

## License

MIT — see [`LICENSE`](LICENSE).

---

*ESE 561 — Artificial Intelligence · Stony Brook University · Spring 2026*
