# Steps

One entry per step. Write the hypothesis and expected fixes **before** running the eval.

### Step 0 · Baseline

Agent: table/column names from `information_schema` + `run_sql` + `submit_answer`.
No docs, no metric definitions, no business rules.

Hypothesis: it answers simple counts but fails on metric definitions (revenue with vs without
tax), table grain (supplies fan-out), time ("last quarter" vs data ending Aug 2025), entities
(stores with no orders) and unanswerable questions.

Predictions per category (written before the first run, 20 questions x 1 run):
- metric-definition (q01-q04): fails q01 (likely sums `order_total`, tax included) and q03
  (likely uses `customer_type = 'new'`). q02 and q04 are a coin flip.
- units (q05): probably passes (marts are in dollars) unless it picks `raw.raw_products`.
- grain (q06-q10): q06 and q07 fail on supplies fan-out; q08 and q09 are likely right; q10 passes if it tries.
- entity (q11-q13): q11 likely says 6 stores; q12 likely says it cannot answer; q13 may use `opened_date`.
- time (q14-q16): q14 divides by 12 or by calendar; q15 and q16 answer instead of asking.
- unanswerable (q17-q20): q19 fails (calls revenue minus supplies "net profit"); q17 may answer from
  midnight timestamps; q18 and q20 are 50/50.
Expected overall: roughly 35-50% (1 run per question, so pass^1 equals the score).

Model: `openai/gpt-oss-120b` on Groq (switched from Gemini, then from llama-3.3-70b-versatile, for higher rate limits, before any
score was recorded).

**Result** (run `step-00-baseline_questions_20261103-130107`, after the q01/q04 eval fix):

Score: **7/20 = 35%** · 8 crashes · tokens/Q: 4,070 · model: openai/gpt-oss-120b

- Recorded as-is and **flagged**: 8 questions crashed on Groq 400 `tool_use_failed` (nonexistent tool `json`,
  prose in the tool arguments, malformed tool name, `run_sql` on the last turn). The harness marks such a run
  INVALID; the scoreboard row was added by hand with `errors=8`. Without the crashes the score would be about 10-11/20.
- Per category: units 100%, metric-definition 50%, grain 40%, entity 33%, time 33%, unanswerable 0%.
- The prediction (35-50%) held, but for a partly different reason: a lot of the loss is infrastructure, not context.
- Decision: the agent was not changed (step 0 stays the control). **Step 1 = recover from rejected tool calls**, so noise is removed before the context fixes are measured.
- Full breakdown: [`eval/analysis/step-00-baseline_20261103-130107/README.md`](eval/analysis/step-00-baseline_20261103-130107/README.md).

**Decision · deterministic evals only, for now.** All 20 questions are graded by code (numbers with tolerance and
unit, sets, `status`). There is no LLM judge and no grading of the agent's reasoning. This is the author's call, to
start improving the agent sooner. A richer eval (an LLM judge with a rubric for free text, reasoning checks) may be added
later, depending on time and on what the agent's results show.

### Eval fix · q01 and q04 (made after the first step-00 run, `step-00-baseline_questions_20261103-094307`)

Reason (author's call, not to make the agent pass; the original run's q01 answer of 671,425.37 would
now be correct, and q04's old gold was 3.52):
- **q01** asked for "revenue" with no definition, so the gold (pre-tax) was an unstated assumption.
  The question now asks for revenue *including sales tax* and the gold is `sum(order_total)`
  (671,425.37). Consequence: q01 no longer tests the tax trap. Pre-tax revenue is still tested by q02, q14 and q16.
- **q04** had `rel_tol: 0.03` to allow 3.52 or 3.59. Tolerance removed (default 0.1%). Customer
  assumption: the 483 $0 orders are ignored, so first/second order are ranked among
  `order_total > 0` orders. Gold changed 3.5199 -> 3.5920.
The step-00 result file predates this fix; re-run step 0 before comparing scores.
