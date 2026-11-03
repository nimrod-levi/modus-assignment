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

Score: _pending, run `make eval STEP=step-00-baseline`_ · tokens/Q: _ · model: openai/gpt-oss-120b

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
