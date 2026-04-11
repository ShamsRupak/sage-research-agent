# SAGE — Self-Adaptive Goal-directed Executor

A multi-tool LLM agent with hierarchical planning and evidence-guided reasoning for automated research synthesis.

## What is SAGE?

Given a complex, open-ended research question, SAGE:

1. **Decomposes** it into a DAG (Directed Acyclic Graph) of sub-goals using a deterministic Python planner
2. **Executes** each sub-goal via a ReAct-style loop with real tools (web search, URL fetching, claim extraction, code execution)
3. **Evaluates** gathered evidence through an Evidence Critic module that scores confidence and detects contradictions
4. **Re-plans** adaptively when evidence is insufficient or contradictory
5. **Synthesizes** all findings into a structured, citation-aware analytical report

All planning and decision-making logic is external to the LLM — the LLM is scoped strictly to per-step reasoning and tool proposal.

## Architecture
User Query
│
▼
┌──────────────────────┐
│  Hierarchical Planner │  ◄── DAG decomposition, priority scheduling, stopping conditions
│  (Deterministic Python)│
└──────────┬───────────┘
▼
┌──────────────────────┐
│  LLM Reasoning Engine │  ◄── ReAct loop: reasoning + tool proposal (per sub-goal)
└──────────┬───────────┘
▼
┌──────────────────────┐
│  Tool Execution Layer │  ◄── web_search, fetch_url, extract_claims, code_run, cross_reference
└──────────┬───────────┘
▼
┌──────────────────────┐
│  Evidence Critic      │  ◄── Confidence scoring, contradiction detection → ACCEPT / RETRY / ESCALATE
└──────────┬───────────┘
▼
┌──────────────────────┐
│  Synthesis & Report   │  ◄── Topological DAG traversal → structured Markdown report
└──────────────────────┘

## Tech Stack

| Component | Technology |
|-----------|-----------|
| LLM | Groq API (`llama-3.3-70b-versatile`) |
| Web Search | Tavily API |
| URL Fetching | `httpx` + BeautifulSoup4 |
| Code Sandbox | `subprocess` with timeout |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| State Management | Pure Python (`dataclasses`, `heapq`) |
| Terminal Output | `rich` |

## Setup

```bash
git clone https://github.com/ShamsRupak/sage-research-agent.git
cd sage-research-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
```

## Usage

```bash
python -m demo.run_demo
```

## Project Status

- [x] Phase 0: Repository and environment setup
- [ ] Phase 1: Core data structures (DAG, state)
- [ ] Phase 2: Hierarchical planner
- [ ] Phase 3: LLM client and prompts
- [ ] Phase 4: Tool layer
- [ ] Phase 5: Evidence Critic
- [ ] Phase 6: Main agent loop
- [ ] Phase 7: Synthesis
- [ ] Phase 8: Demo
- [ ] Phase 9: Evaluation and ablation
- [ ] Phase 10: Final report

## Team

- **Shams Rupak** — Hierarchical Planner, priority scheduler, DAG, ablation study, evaluation
- **Gagan Sapkota** — Tool layer, Evidence Critic, state/memory, synthesis, demo

## License

Academic project for ESE 561 — Artificial Intelligence, Stony Brook University.
