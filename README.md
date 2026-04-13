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
|-----------|------------|-----|
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
├── demo/
│   └── run_demo.py            #   End-to-end demo
├── report/
│   ├── main.tex               #   Final report
│   └── proposal.tex           #   Proposal
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
 
Results from actual measured runs across three queries:
 
**Query q1** — *Transformer vs. RNN architectures (hard)*
 
| Metric | SAGE | Flat ReAct | Single LLM |
|--------|------|------------|------------|
| Sub-goals | 5 | 1 | 1 |
| LLM Calls | 28 | 8 | 1 |
| Tool Calls | 19 | 5 | 0 |
| Avg Confidence | 0.82 | 0.50 (default) | 0.00 |
| Retries | 0 | 0 | 0 |
| Citations | 14 | 3 | 0 |
| Report Length | 8,500 chars | 3,200 chars | 7,223 chars |
| Time (s) | 135 | 42 | 3 |
 
**Query q2** — *Reducing LLM hallucination (hard)*
 
| Metric | SAGE | Flat ReAct | Single LLM |
|--------|------|------------|------------|
| Tool Calls | 30 | 0 | 0 |
| Avg Confidence | 0.83 | 0.50 (default) | 0.00 |
| Retries | 2 | 0 | 0 |
| Citations | 93 | 0 | 0 |
| Report Length | 15,027 chars | 579 chars | 5,866 chars |
| Time (s) | 285 | 13 | 6 |
 
**Query q5** — *RAG vs. fine-tuning comparison (medium)*
 
| Metric | SAGE | Flat ReAct | Single LLM |
|--------|------|------------|------------|
| Sub-goals | 6 | 1 | 1 |
| LLM Calls | 54 | 4 | 1 |
| Tool Calls | 37 | 3 | 0 |
| Avg Confidence | 0.85 | 0.50 (default) | 0.00 |
| Retries | 3 | 0 | 0 |
| Citations | 80 | 0 | 0 |
| Report Length | 12,855 chars | 1,059 chars | 4,779 chars |
| Time (s) | 317 | 11 | 3 |
 
Key findings across all runs: SAGE consistently achieves **0.82–0.85 confidence** with **14–93 citations**, while both baselines produce **zero verified citations**. The Evidence Critic triggered **retries on q2 (2) and q5 (3)**, directly demonstrating self-correction. The q2 hallucination query is especially telling — SAGE produced 93 grounded citations on a topic specifically about reducing ungrounded claims.
 
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

**59 tests passing** · **16 modules** · **~15 commits**

---

*ESE 561 — Artificial Intelligence · Stony Brook University · Spring 2026*
