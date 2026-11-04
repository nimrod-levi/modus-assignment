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

### Step 1 · Remove tool-call rejections (infrastructure only)

Root cause (from `failed_generation` in the step-0 and step-1 runs): gpt-oss addresses its final JSON to a recipient
that is not in our tools list (`json`, `commentary`: names from its output format, not tools), and Groq rejects the reply
with 400 `tool_use_failed`. In some cases (q08, q20) the "call" was plain prose. Asking for a JSON answer through a
tool while tools are present is the trigger (to be confirmed by the eval; not yet verified against Groq docs).
First attempt (clearer prompt + capped retries) still had 10 rejections over 6 questions; q07 and q16 used all 3 retries.

Changes (tool contract only, no business context):
- `run_sql` is the only tool. A reply with no tool call means "done".
- The final answer is a separate request with no tools and a strict `json_schema` response format (`ANSWER_FORMAT`).
  Same fields as before; optional ones are nullable because strict mode needs all fields required.
- The system prompt has no "JSON" wording.
- Safety net kept: a rejected reply is sent back with feedback and retried, `max_retries = 3` per question, then
  `end_reason = "api_error"`.
- Scoring: each rejected call costs 10% of that question's credit (`1 - 0.1 * rejections`, only for passed questions).
  `score` is the penalized headline; `raw_score` is the plain pass rate; `rejections` is logged. Assumption: per question.

Hypothesis: rejections go to about 0 (before: 10 over 20 questions). Score is about 10-12/20 (50-60%): q04 q06 q08 q10 q11 q12
run to the end. Wrong answers q02 q16 q17 q18 q19 stay wrong (they need context, steps 2+). Unknown: whether Groq accepts
strict `json_schema` on `openai/gpt-oss-120b`; if it does not, the final call needs a plain `json_object` format.
Not fixed here: q04 hit a 413 (8,000 tokens/min cap on Groq's free tier; results fed back to the model are too big).
Smoke check (not a score): single runs on `openai/gpt-oss-20b` after the 120b daily token limit was hit: q10 and q07 both
ended `submitted` with 0 rejections, so Groq accepts the strict `json_schema` final request. Not run on the 120b yet.
**Provider switch note (infra, not a step).** The agent now calls `openai/gpt-oss-120b` through OpenRouter (OpenAI SDK, base URL
`https://openrouter.ai/api/v1`, `provider.require_parameters = true`) instead of Groq, for a bigger usage plan. Step 0 was **not**
re-run: its 7/20 and the 8 `tool_use_failed` crashes were measured on Groq and are kept as recorded. Same model slug, but a
different serving stack, so step 0 -> step 1 now mixes the context/tool change with a provider change. Read that delta with
this caveat. Each trace now records the serving `provider`. The provider is pinned (`OPENROUTER_PROVIDER`, default Cerebras, `allow_fallbacks=false`): unpinned, OpenRouter routed to
providers that ignore the strict `json_schema` final request (DeepInfra: empty content; CoreWeave: runaway output; Nebius, Groq-via-OpenRouter: empty),
while Together, Parasail, BaseTen, Crusoe, AkashML and Cerebras returned valid JSON in a one-request probe.
Reasoning effort is also set explicitly (`OPENROUTER_REASONING_EFFORT`, default `medium`): an aborted first run on Together's default
effort used about 10x the output tokens of the Groq step-0 run (1k-19k vs 0.2-0.9k per question), so it was slow. That run was
stopped at 8/20 and is not a score. Speed on one question (q01): Together medium 14.9s, Together low 4.2s, Cerebras medium 1.4s,
so the default provider is Cerebras (fast, fp16, valid final JSON in the probe), at medium effort.

**Result** (run `step-01-tool-recovery_questions_20261103-221238`, gpt-oss-120b via OpenRouter/Cerebras, medium effort):

Score: **13/19 = 68.4%** · 0 errors · 0 rejections · 19,090 tokens/Q. Full analysis: `eval/analysis/step-01-tool-recovery_20261103-221238/`.

- Crashes gone: every question reached a final answer. q08 q10 q11 q12 now pass, as predicted.
- Still failing, as predicted: q15-q20 (time and unanswerable). They need context, steps 2+.
- Surprise: q02 and q06 pass although the context did not change. Probably run-to-run variance (1 run); treat as unstable.
- Not a clean delta from step 0: the provider changed (Groq to Cerebras) and the set is 19 questions, not 20.

**Eval fix: q04 disabled** (commented out in `eval/questions.yaml`, author's decision). Reason: it takes too many tokens to explain the
assumptions (ignore $0 orders, tolerance) and the agent is unlikely to get it right anyway. Not tuned to a score: it is removed for
every step from here on, so step 0 (20 questions) is not strictly comparable. Re-enable it when the glossary exists.

### Step 2 · Optimization: fewer tokens, fewer calls, max 5 rows (infrastructure, no business context)

Where step 1's tokens went (from `results/step-01-tool-recovery_questions_20261103-221238.json`): mean 19,090/Q is
misleading. The median is about 4.7k; one question (q20) used 202k (11 SQL calls, up to 200 rows each, all re-sent every turn).
Input tokens are about 90% of the total. A one-query question already costs about 3.3k: the ~1k-token schema prompt is re-sent on
each of 3 requests (query, "Done.", final answer). So the cost drivers are (1) rows in tool results, which are
re-sent on every later turn, (2) the number of turns, (3) the size of the fixed prompt.

Changes (same model, same questions, same context; no business knowledge added):
- `run_sql` returns at most **5 rows** (was 200), cells cut at 60 chars (was 120). The truncation note tells the model to aggregate in SQL.
- **Assumption when truncated:** if any query in a run hit the cap, the harness appends to the answer's `assumptions`:
  "Only the first 5 rows were retrieved; a full listing is not a requested feature, ask if you need it." Added in code, not left to the model.
- Fewer calls: the prompt asks for one aggregating query and for independent queries to be sent together
  (the loop already runs several calls per turn; no API parameter added, to avoid provider rejections); an identical SQL repeated within a question gets a one-line reply instead of the rows again.
- Smaller fixed prompt: type precision and long type names dropped from the schema listing (`DECIMAL(38,2)` -> `decimal`).
- The system prompt no longer tells the model to reply "Done."; it is only told to stop calling tools. (The extra no-tool turn
  still exists; removing it is a loop change, left for later.)
- Not changed, to keep the delta clean: reasoning effort, provider, model, prompt caching.

Hypothesis: tokens/Q falls from 19,090 to about 6-9k (mostly the q20-type outliers), SQL calls/Q from 4.0 to about 3, and the score
stays at 13/19 +/- 1 (1 run per question, step 1 already showed q02/q06 are unstable). q07 and q13 (set answers, 1-row golds) must not break.
Risk: a question that needs a long list sees only 5 rows; none in the eval does. If the score drops by 2 or more, look at traces
for "truncated" before blaming variance.

**Result** (run `step-02-optimization_questions_20261103-224026`, same model/provider as step 1):

Score: **13/19 = 68.4%** (unchanged) · 0 errors · **7,043 tokens/Q (was 19,090, -63%)** · **2.5 SQL calls/Q (was 4.0)**.

- Hypothesis held: tokens fell into the predicted 6-9k band and calls fell below 3; score did not regress. q07 and q13 still pass.
- Same questions fail as in step 1 (q15-q19 need context, steps 3+); q20 now passes and one other question flipped. With 1 run/question that is variance, not a gain: read the score as "no regression".
- Not measured here: how often the truncation assumption was added (no eval question needs a list). Still open: the extra no-tool turn before the final answer, reasoning effort, prompt caching.

### Eval fix · q04 re-enabled (made before step 3)

Reason (author's call): q04 was disabled after step 1 because explaining its assumptions cost too many tokens. It is back so the eval
has 20 questions again. Question text, gold SQL and tolerance are unchanged from the disabled version. Consequence: steps 1 and 2
(19 questions) are not strictly comparable to anything from step 3 on. Re-run step 2 on the 20 questions to get the baseline for step 3.
The $0-order assumption is still not in the prompt (it is a customer answer, so it belongs in the glossary step); q04 is expected to fail until then.

### Decision · Cube (`cube_dbt`) considered as the semantic layer, not used

`cube_dbt` (PyPI) only turns `manifest.json` into Cube YAML with dimensions (name, type, description, `meta`, primary-key tag). It
generates no measures and no joins, and it needs a running Cube server for the agent to query through. Measures and joins would be written
by hand, which breaks "context must be generated", and a second modeling language plus a server is more than a 25-minute review can cover.
The repo already has the semantic layer in dbt (`semantic_models` and `metrics` in the mart YAML, compiled to
`target/semantic_manifest.json`), so we generate from dbt directly. Revisit only as a spike if the generated context stalls.

### Step 3 · Generated structural context (grain, keys, joins, data facts)

Root cause targeted: the agent only sees column names and types, so it cannot know the grain of a table, which joins fan out, the date
range of the data, or which stores have orders. Everything below is generated from `dbt/target/manifest.json` and the warehouse
(`agent/semantic.py`); no business rule is typed into the prompt.

Changes (same model, provider, tools; only the schema block of the system prompt changes):
- Per mart table: row count, grain ("one row per X", from `unique` tests; marts inherit the tests of their `stg_` model), dbt table and column descriptions.
- Join paths: declared (dbt `relationships` tests) plus inferred (a column named like another table's key, labelled "(inferred)").
- Join cardinality lines with a fan-out warning, and the parents with no children (e.g. "4 of 6 locations rows have no orders rows").
- Data facts read from the warehouse: min/max of every date column, values of text columns with at most 6 distinct values.
- Staging and raw tables stay as the compact one-line listing. Not changed: tools, model, provider, reasoning effort, row cap.

Hypothesis: prompt grows from about 1k to about 1.4k tokens, so tokens/Q rises by roughly 1-2k (more than the 3 requests x 0.4k, because the
model may also run fewer exploratory queries). Score on the 20 questions rises by 1-3 over the step-2 re-run:
- likely fixed: q11 q12 (stores without orders, now stated), q15 (the data ends 2025-08-31, now stated), q01/q02 (the tax is in `order_total`'s description);
- grain questions (q06 q07 q09) should hold or become more stable (fan-out warning);
- not expected to move: q04 (customer assumption), q17-q20 (unanswerable: the context says what exists, but nothing tells the model to refuse), q03 (definition of "new").
If the score does not move, read the traces before concluding: the missing piece may be the metric definitions (step 4, MetricFlow), not structure.
