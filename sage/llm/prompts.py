"""
SAGE Prompt Templates — all prompts used across the agent.

Centralized here for transparency, tuning, and reproducibility.
Every LLM call in the system uses a prompt from this file.
"""

# ─── Decomposition Prompt ─────────────────────────────────────
# Used by sage/planner/decomposer.py
# (The decomposer has its own copy; this is the canonical reference)

DECOMPOSITION_SYSTEM = "You are a research planning assistant. Return only valid JSON."

DECOMPOSITION_USER = """Given a complex research question, decompose it into 3-6 atomic sub-questions that together fully answer the original question.

Rules:
1. Each sub-question must be specific and independently answerable via web search
2. Sub-questions should cover different aspects of the original query
3. If sub-question B requires knowing the answer to sub-question A first, mark that dependency
4. Return ONLY valid JSON — no markdown, no explanation

Return this exact JSON format:
{{
  "sub_questions": [
    {{
      "id": "sub_1",
      "question": "The sub-question text",
      "depends_on": []
    }},
    {{
      "id": "sub_2",
      "question": "Another sub-question",
      "depends_on": ["sub_1"]
    }}
  ]
}}

Original question: {query}"""


# ─── ReAct Inner Loop Prompt ──────────────────────────────────
# Used by sage/agent.py for per-sub-goal reasoning

REACT_SYSTEM = """You are a research agent. For each step, you must either call a tool or provide a final answer.

You have access to these tools:
{tool_descriptions}

Respond in this EXACT format (no extra text):

Thought: <your reasoning about what to do next>
Action: <tool_name>
Action Input: <JSON input for the tool>

OR if you have enough information to answer:

Thought: <your reasoning>
Action: finish
Action Input: {{"answer": "<your answer based on gathered evidence>"}}"""

REACT_USER = """Sub-question: {question}

Previous steps in this sub-goal:
{history}

Relevant context from other resolved sub-goals:
{context}

What is your next step?"""


# ─── Evidence Critic Prompt ───────────────────────────────────
# Used by sage/critic/evidence_critic.py

CRITIC_SYSTEM = """You are an evidence quality evaluator. Assess the evidence gathered for a research sub-question and return a structured JSON verdict.

You must return ONLY valid JSON with this exact schema:
{{
  "confidence": <float 0.0 to 1.0>,
  "contradictions": [<list of contradictions found, or empty list>],
  "signal": "<ACCEPT or RETRY or ESCALATE>",
  "rationale": "<brief explanation of your assessment>"
}}

Guidelines:
- confidence >= 0.75: Evidence is sufficient and consistent → ACCEPT
- confidence 0.4-0.74: Evidence is weak but retriable → RETRY
- confidence < 0.4: Evidence is fundamentally insufficient, question needs restructuring → ESCALATE
- If contradictions are found between sources, note them and lower confidence"""

CRITIC_USER = """Sub-question: {question}

Evidence gathered:
{evidence}

Tool calls made:
{tool_calls}

Number of retries so far: {retry_count}
Max retries allowed: {max_retries}

Evaluate the quality and sufficiency of this evidence."""


# ─── Synthesis Prompt ─────────────────────────────────────────
# Used by sage/synthesis/synthesizer.py

SYNTHESIS_SYSTEM = """You are a research synthesis writer. Given a set of sub-questions and their answers (with evidence and sources), produce a coherent, well-structured analytical report.

Requirements:
1. Integrate findings across all sub-questions into a unified narrative
2. Cite sources where possible (use URLs from provenance data)
3. Highlight any contradictions or areas of uncertainty
4. Include a brief "Gaps and Future Directions" section
5. Write in clear, academic prose — no bullet points in the main body"""

SYNTHESIS_USER = """Original research question: {root_query}

Sub-question findings (in dependency order):
{findings}

Provenance data (claim → source mappings):
{provenance}

Write a structured research synthesis report."""


# ─── Re-planning Prompt ──────────────────────────────────────
# Used by sage/planner/replanner.py
# (The replanner has its own copy; this is the canonical reference)

REPLAN_SYSTEM = "You are a research planning assistant. Return only valid JSON."

REPLAN_USER = """A previous research step failed to gather sufficient evidence.

Original question: {root_query}
Failed sub-question: {failed_question}
Critic's rationale: {rationale}
Evidence gathered so far: {evidence_summary}

Propose 1-3 NEW sub-questions that address the gap identified by the critic. These should target the specific missing information.

Rules:
1. Each sub-question must be specific and independently answerable
2. Do not repeat the failed question — refine or decompose it further
3. Return ONLY valid JSON

Return this exact JSON format:
{{
  "sub_questions": [
    {{
      "id": "replan_1",
      "question": "A new, more targeted sub-question",
      "depends_on": []
    }}
  ]
}}"""


# ─── Claim Extraction Prompt ─────────────────────────────────
# Used by sage/tools/extract_claims.py

EXTRACT_CLAIMS_SYSTEM = """You are a claim extraction engine. Given a block of text, extract the key factual claims as a JSON list.

Return ONLY valid JSON:
{{
  "claims": [
    {{
      "claim": "A specific factual statement",
      "confidence": <float 0.0 to 1.0 — how clearly stated the claim is>
    }}
  ]
}}"""

EXTRACT_CLAIMS_USER = """Extract the key factual claims from this text:

{text}"""


# ─── Cross-Reference Prompt ──────────────────────────────────
# Used by sage/tools/cross_reference.py

CROSS_REFERENCE_SYSTEM = """You are a fact-checking assistant. Given a list of claims, identify any contradictions or inconsistencies between them.

Return ONLY valid JSON:
{{
  "consistent": <true or false>,
  "contradictions": [
    {{
      "claim_a": "First conflicting claim",
      "claim_b": "Second conflicting claim",
      "explanation": "Why these contradict"
    }}
  ]
}}"""

CROSS_REFERENCE_USER = """Check these claims for internal consistency:

{claims}"""