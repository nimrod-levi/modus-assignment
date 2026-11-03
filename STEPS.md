# Steps

One entry per step. Write the hypothesis and expected fixes **before** running the eval.

### Step 0 · Baseline

Agent: table/column names from `information_schema` + `run_sql` + `submit_answer`.
No docs, no metric definitions, no business rules.

Hypothesis: it answers simple counts but fails on metric definitions (revenue with vs without
tax), table grain (supplies fan-out), time ("last quarter" vs data ending Aug 2025), entities
(stores with no orders) and unanswerable questions.

Model: `llama-3.3-70b-versatile` on Groq (switched from Gemini for higher rate limits, before any
score was recorded). 1 run per question.

Expected: simple counts pass; most failures come from the missing business context listed above.
Unanswerable questions (`status` grading) fail because nothing tells the agent when to refuse.

Score: _pending, run `make eval STEP=step-00-baseline`_ · tokens/Q: _ · model: llama-3.3-70b-versatile
