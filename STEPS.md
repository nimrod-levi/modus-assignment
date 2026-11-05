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

**Result** (run `step-03-structural-context_questions_20261104-080457`, commit `a7ddb3e`, analysis in `eval/analysis/step-03-structural-context_20261104-080457/`):

Score: **10/20 = 50.0%** (10/19 on the questions shared with step 2, down from 13/19) · 0 errors · **10,191 tokens/Q (was 7,043, +45%)** · 2.45 SQL calls/Q.

- **Hypothesis rejected.** Predicted +1 to +3 and +1-2k tokens; got -3 and +3.1k. Only q06 (a gap in the generated fan-out warning: it covers parent columns, not two tables sharing a key) and probably q03 (the dbt description of `customer_type` was applied literally) can be blamed on the context.
- q08 failed only because the grader rejected the unit "drink items" (value correct); q02 (P,F,P) and q20 (F,P,F) flipped across steps 1-3, so they are noise.
- q15-q20 did not move: the context says what exists, but nothing says to decline when a concept has no data. q15 now cites the data range to justify a guess.
- Conclusion: not a verdict on step 3 yet. With 1 run per question the comparison is inside the noise. Next: re-run step 2 on 20 questions and step 3 with `RUNS=3`, fix the generator gaps, then add the refusal rule as its own step.

### Step 3b · Refusal rule in the system prompt (added by the author after the step-3 analysis)

Change: one generic sentence added to `SYSTEM_PROMPT`: if no table or column holds the concept asked for, answer `cannot_answer`, no
proxy; if the question is ambiguous, ask. Not tied to any eval question. Note for honesty: it was written after reading the step-3
failures (q15-q20), so it targets them by design; the holdout set (`make eval-holdout`) is the check that it does not just fit the eval.

**Result** (run `step-03-structural-context_questions_20261104-081304`, prompt sha `f305e7d7e1fb`): **14/20 = 70.0%** · 0 errors ·
**7,478 tokens/Q (was 10,191)** · 1.5 SQL calls/Q.
- Fixed vs the first step-3 run: q18 (refund rate) now declines. q20 declines too, q06 and q08 pass again (those two flipped back: noise, not the rule).
- Still failing: q03 (`customer_type = 'new'` filter), q04 (glossary), q15 and q16 (answered instead of asking: the rule is not enough for relative dates and partial quarters), q17 (hour 0 from midnight-only timestamps), q19 (net profit from supply costs only).
- Tokens fell by a third with the same context: the model needs fewer exploratory queries when it declines early. Read it with 1 run per question in mind.

### Step 3c · Table notes layer (generated warnings per table)

Root cause targeted: q15 q16 q17 (and q06 earlier) fail on facts about the data that the model can compute but does not think to check: the data
ends 2025-08-31 with no "today", Q3 2025 holds only July-August, timestamps are all midnight, two tables joined through the same key repeat rows.
Change (`agent/semantic.py`, `table_notes`, `sibling_warnings`; all read from the warehouse, nothing typed by hand): each table gets `NOTE:` lines:
- date columns: range, number of months, calendar quarters that are incomplete, "date only: every value is midnight", "no 'today' is stored";
- columns that are null for the same rows (grouped), money/count columns equal to 0 in up to 5% of rows (grouped);
- parents with no children ("4 of 6 rows have no orders rows");
- a many-to-many warning for tables that reference the same parent key (order_items and supplies via products).
The column-level date ranges moved into the notes, and the per-join "N of M have no children" sentence moved into the parent's notes.
Prompt grows from about 1.5k to about 1.75k tokens.

Hypothesis (vs the step-3b run, 14/20): +2 to +3 questions. Likely: q17 (midnight note), q16 (incomplete Q3 note), q06 stays fixed (sibling warning).
Possible: q15 (the "no today" note). Not expected: q03, q04 (definitions, glossary), q19 (no generated fact says costs other than supplies are absent).
Risk: more prompt tokens per request; notes the model reads as instructions instead of facts. Run with `RUNS=3` and compare with 3b at `RUNS=3`.

**Result** (run `step-03c-table-notes_questions_20261104-082123`, commit `02db363`, 3 runs per question): **66.7% mean score (13.3/20)** ·
pass^3 = 65.0% (13 questions pass all 3 runs) · 0 errors · **8,670 tokens/run (3b: 7,478)** · 1.4 SQL calls/run.
- Hypothesis: partly held. **q17 is fixed and stable (3/3)**: the "every value is midnight" note works. q06 stays unstable (PFF).
  q15 and q16 did not move; q19 did not move, as expected.
- Not comparable to 3b's 14/20: that was one run, this is the mean of three. The 3b-at-3-runs baseline was not run, so the effect of 3c alone
  is not measured. To measure it: check out `7b8e886` and run `make eval STEP=step-03b-refusal-rule RUNS=3`.
- q16: the model now reads the note ("the data only includes July and August for Q3") and writes it into `assumptions`, but still gives the
  -66,204 figure instead of asking. The facts reached the model; the behaviour did not change. Whether answering with that caveat should count
  as a fail is a grader question for the author, not something to tune here.
- q15: it states "most recent full month in the dataset" and answers. Same pattern: the note is used to justify a guess.
- q06 run 2: after a binder error it deduplicated `(order_item_id, supply_cost)` to avoid the fan-out and got 131,788.38 (equal to
  `sum(order_cost)`), because the join to `supplies` still filters wrongly. The sibling warning was in the prompt; the model reasoned about it and still chose the wrong fix.
- q08 fails 3/3 on the unit "drink items" (value correct): the grader unit list, still undecided. q03, q04 need the glossary.
- Tokens: +1.2k/run vs 3b, in line with the 0.25k larger prompt sent on about 3 requests plus more reading.

### Eval fix · q08 unit list (made after step 3c)

Reason (author's call): q08 failed in every step-3 run only because the answer's unit was "drink items", which the grader did not accept
although the value (70,819) is correct. `drink items` added to the allowed units (`drinks`, `items`). Question text, gold SQL and number
tolerance are unchanged. Effect: q08 results from step 3 onward are scored with the new list; earlier result files keep the old verdict
(re-grade them if a table across steps is needed).

### Author's note · concern about the step 3 approach (written after step 3c)

The author does not like the direction of steps 3b/3c. Each fix (the refusal sentence, the midnight-timestamp note, the partial-quarter note,
the sibling fan-out warning) was chosen because an eval question failed. They are generated from the data, not typed per question, but
the *choice of what to look for* still comes from the failures we saw. Gaps the eval does not cover will be missed, and the score
then overstates how well the agent understands the data. The holdout set (`make eval-holdout`) is only a partial check.

Possible direction for later: start from a systematic definition of data edge cases instead of from failures, e.g. a fixed checklist
run on every table and column (coverage and gaps in time, granularity of timestamps, nulls, zero/negative values, duplicates, orphan
keys, many-to-many paths, units and scale, values that look like placeholders, concepts the schema cannot represent), emitted as
notes. The checklist would be written before looking at any eval result and would be reviewed on its own merit. Not started; decide
after the holdout run and the 3b-at-3-runs baseline.

### Step 3d · Edge-case checklist replaces the hand-picked notes (answer to the author's note above)

Change: `agent/edge_cases.py` is a fixed checklist of 11 checks, run on every mart table and column (`make checks` prints the result):
date ranges, time coverage (missing months, partial first/last month, incomplete quarters, no "today"), time of day, nulls, zeros,
negatives, duplicate keys/rows (or no key declared), orphan and childless keys, constant columns, placeholder values, scaled duplicate
columns (x_cents vs x). Join-level fan-out and many-to-many risks come from the join graph (`join_risks`). It replaces `table_notes` and
`sibling_warnings` in `agent/semantic.py`; the column descriptions, grain, joins and the refusal sentence in the system prompt are unchanged.
- Every table now also gets a line "Checked, nothing found: ...". A check that does not apply (no date column) is not listed. The agent can
  tell "no negatives" from "nobody looked", which the sentence-per-gap notes could not say.
- Each check is unit-tested on planted data (`tests/test_edge_cases.py`), not only on the jaffle-shop data, to show it does not depend on this dataset.

Honest limits:
- The checklist was written after seeing the step-3 failures, so time coverage and time of day are on it partly because we saw them fail.
  The other nine come from the usual data-quality taxonomy and fire on nothing in the eval; whether they help is untested here.
- Not covered by design: concepts the schema does not hold (refunds, targets, costs other than supplies), metric meaning, fiscal calendar
  (glossary). Not covered yet: outliers, near-duplicate text, cross-column consistency. So q19 (net profit) and q15 (what is "today") stay open.
- New findings that appear (the cents columns, the 483 rows with a 0 total, `count_drink_items = 0`) are facts the model may over-read.

Hypothesis (vs step 3c, 66.7% mean over 3 runs): score within +/-1 question of 3c, because the findings the eval depends on (midnight, partial
Q3, stores without orders, sibling join) are the same ones as before, now produced by general checks. A clear change would mean the extra
generic findings help or hurt, which is the thing to look at in the traces. Tokens: about +0.1k to +0.3k per request (the "Checked, nothing found"
lines and the cents note). Run with `RUNS=3`; compare also with the 3b baseline at `RUNS=3`.

**Result** (run `step-03d-edge-case-checklist_questions_20261104-083512`, commit `deffa23`, analysis in `eval/analysis/step-03d-edge-case-checklist_20261104-083512/`):

Score: **15/20 = 75.0%** · 0 errors · **11,506 tokens/run (3c: 8,670)** · 2.0 SQL calls/run. **1 run per question, chosen to save tokens; this is not optimal**
(single questions flipped between runs in steps 1-3), so read it as +/- 1-2 questions.
- Hypothesis (within +/-1 of 3c) held on the questions the checklist can affect: q17 stays fixed, q03 q04 q15 q16 q19 fail as before. The two differences
  from 3c are not checklist effects: q08 passes because of the unit eval fix (3c would score about 71.7% with it), and q06 is unstable (1 of 3 in 3c).
- Tokens +33% vs 3c with no measured gain; the "Checked, nothing found" lines are the first candidate to cut.
- What this shows: the checklist reproduces the 3c finding through general checks with no loss. It does not show the checklist finds anything the eval does not test; run the holdout.

### Step 3 · wrap-up

Step 3 went from "no context" (13/19) to generated structure (10/20), a refusal sentence (14/20), hand-picked notes (66.7% over 3 runs) and the
edge-case checklist (15/20). The remaining failures are definitions (q03 q04), an undefined "today" and partial periods (q15 q16) and a missing concept
(q19). None is a structure problem. Next: holdout run, then the glossary step, then the metric tool. Tag `step-03-structural-context` was not placed yet.

### Step 4a · Customer glossary (all entries sent with the question)

Change: `glossary/glossary.yaml` holds 10 customer-provided entries (the author's defaults until the customer, Maya, confirms them) (kinds: definition, rule, reference), kept apart from the
generated context. `agent/glossary.py` validates the file against the warehouse (`make glossary-check`: required fields, kinds, duplicate ids,
`applies_to` tables and columns exist, `sql` snippets compile) and renders a labelled block. The block is added to the first user message, after
the question, not to the system prompt. The trace records `glossary_ids`. Switch: `GLOSSARY=off|all` (default `all`); `off` reproduces 3d.
- The 10 entries are the author's assumptions: revenue (pre-tax, state the definition in every answer), revenue incl. tax, new customer, fiscal year,
  empty orders, Brooklyn's open date, customer identity, relative dates, partial periods, gross profit. **Every entry is
  `assumed`**: the customer has not answered. The block shows `(assumed)` to the agent.
- q15 and q16 stay as the grader has them: the glossary says the data ends 2025-08-31 and to ask for relative periods, and to ask before comparing an
  incomplete period. This is a customer rule, not a way to edit the gold. If the customer says "today is 2025-09-01", the right answer for q15 changes
  and that would be an eval fix with its own commit.

Honest limits:
- By the author's decision the glossary does NOT list what the warehouse lacks (refunds, targets, costs other than supplies, order times, net profit): the agent
  has to find that out itself, as in 3d. So q19 (net profit) is not expected to move; it stays the open "missing concept" case.
- Several entries (new customer, empty orders, relative dates, partial periods) match questions that failed (q03 q04 q15 q16), so a gain on q03 q04 only shows that a given definition fixes a
  definition error. It does not show the agent finds such gaps itself. The holdout run is the fairer test.
- Risk of regressions: `empty_orders` is broad (counts, averages and sequence), so it can change questions that count orders or customers (q09 q13 q14);
  the gold for those includes the $0 orders. `revenue` could push q01 toward the pre-tax subtotal; `revenue_incl_tax` says to use order_total when asked.
  `revenue` also asks for the definition in every answer, which adds output tokens.

Hypothesis (vs 3d, 15/20 at 1 run, 11.5k tokens/run): **17/20** (q03 and q04 fixed; q19 unchanged). q15 and q16 are expected to improve
(the glossary tells the agent to ask), so 18-19/20 is possible. Tokens: about +0.4k to +0.8k per question (the full block is ~500 tokens, read on
most turns of the conversation). Any regression in q01 q09 q13 q14 would be the cost of the wording. Run: `make eval STEP=step-04a-glossary-all`
(1 run, not optimal), then `make eval-holdout STEP=step-04a-glossary-all` and the same holdout run for 3d as its baseline.

**Result** (run `step-04a-glossary-all_questions_20261104-095159`, commit `a865982`, analysis in `eval/analysis/step-04a-glossary-all_20261104-095159/`):

Score: **16/20 = 80.0%** (3d: 15/20) · 0 errors · **10,191 tokens/run (3d: 11,506)** · 1.1 SQL calls/run. 1 run per question, not optimal.
- Hypothesis (17/20) not met by one question: q03 fixed; q04 applied the $0-order rule but the agent rounded `numeric_value` to 3.6 (gold 3.592034, tolerance 0.1%).
  No regression on the 15 questions that passed in 3d (q09 q13 q14 held, so the broad `empty_orders` wording did no harm in this run).
- **New failure:** q15 q16 q19 make 0 SQL calls and report invented figures (q15 "$1,234,567.89"). In 3d they queried. The glossary entries for q15/q16 say to ask or
  state a limit; the agent states it and answers anyway, without a query. One run; check with RUNS=3 on those three before reacting.
- Tokens: median +0.8k per question as predicted; the lower mean comes from q07/q13 using fewer calls and from the three no-query answers. Not a saving.
- Shows that a customer definition fixes a definition error (q03). Does not show the agent finds such gaps itself; the holdout run has not been done.

Next (step 4b): choose the entries per question with embeddings (OpenRouter embeddings work with the OpenAI SDK; spike done with
`openai/text-embedding-3-small`: 1536 dims, about $1e-7 per call), always-on `reference` entries, top-k above a threshold, vectors cached on disk.
Expected: the same score with fewer tokens. With 12 entries the gain is tokens, not score.

### Eval fix · q04 wording asks for the exact value (made after step 4a, author's call)

Reason: in step 4a q04 failed only because the agent rounded. Its query returned 3.592034..., it applied the $0-order rule correctly, and it
submitted `numeric_value` 3.6, which is 0.25% off against the 0.1% tolerance. The question asked for "on average, how many days" and never said how
precise. The author changed the wording to "how many days pass **exactly** between ..." to see whether the agent understands that it must not round
when an exact figure is asked for.
- Changed: the question text only. Gold SQL, the $0-order assumption and the grader (unit `days`, default tolerance) are unchanged. No slack was added.
- It is a hint. The new word makes the question easier than the old one, so a q04 pass from now on is not comparable to the q04 fails in steps 3c, 3d and 4a.
  Those result files keep the old wording and the old verdict; the 4a score stays 16/20.
- It is a change made after seeing a failure, which is what the rules discourage. It is logged here, in its own commit, and it is not used to claim a gain:
  when q04 passes, the gain belongs to the wording, not to the glossary.
- What to look for in the next run: that `numeric_value` is 3.592034... and not 3.6. If it is still rounded, the question wording is not the lever, and the
  answer-schema description ("unrounded") is the next candidate.

### Author's note · edge cases and ranges must become dynamic (written after step 4a)

The edge-case checklist (`agent/edge_cases.py`) and the data facts in `agent/semantic.py` (date ranges, partial periods, row counts, values) are computed
when the prompt is built, so they follow the data as long as the data does not change between runs. The author notes that the real warehouse will not
be static: the ranges will move, new months will arrive, new stores will start selling, and a context built once (or cached) goes stale. Edge cases,
ranges and the rest of the generated context will have to be recomputed as the data changes (for example on every new load, or with a freshness
check on the cached context). **Left for later; not started and not part of step 4.**

### Step 4a' · The glossary holds concepts only (author's decision, after the 4a score)

The author removed every specific date, name and example from `glossary/glossary.yaml`: the glossary says what a word means, not what the data
contains. Facts about the data (the last date, which quarter is incomplete, which store opened late, that names repeat) belong to the generated context,
which can follow the data (see the note above). Changes:
- `relative_dates`: no longer says the data ends on a given date; it says the last date in the data is not today, so ask and state that date.
- `partial_periods`: no longer names Q3 2025; it says that if the data covers only part of a period, say so and ask before comparing.
- `brooklyn_open_date` is now `store_start_date`, without the store name or date: trust the store's first order over `locations.opened_date`, flag a gap.
- `customer_identity`: "(names repeat)" removed.

What this tests: whether the agent can combine a concept ("a partial period needs a question") with the facts in the generated context (which period is
partial), instead of reading both from one sentence. The 4a score came partly from entries that carried the answer's data; this removes it.
Expectation: q03 and the 15 stable questions hold. q15 and q16 may get worse or better: the model must now find the last date by itself (a query), which could
also reduce the no-query answers seen in 4a. This is a new run, so a new score: `make eval STEP=step-04a2-glossary-concepts`; the 4a result stays as measured.

**Result** (run `step-04a2-glossary-concepts_questions_20261104-101246`, commit `ce6f329`, analysis in `eval/analysis/step-04a2-glossary-concepts_20261104-101246/`):

Score: **18/20 = 90.0%** (4a: 16/20, 3d: 15/20) · 0 errors · **10,822 tokens/run** (4a: 10,191) · 1.4 SQL calls/run. 1 run per question, not optimal.
- q04 passes with the new "exactly" wording, but the answer is still rounded (3.59 vs 3.592034); the 0.1% tolerance absorbed it. The 4a to 4a' step is not clean for that reason:
  without q04 it is 17/19 vs 16/19, +1 (q15).
- q15 passes: the agent asks which month is meant and states the last date in the data, taken from the generated ranges. The split concept (glossary) and fact (generated) works.
- q16 fails again with 0 SQL calls and invented figures (second glossary run in a row). q19 now queries but treats `tax_paid` as a cost (73.99%).
- Removing the dates from the glossary lost nothing in this run.

### Author's note · the glossary does not scale and holds assumptions (written after step 4a')

1. **Proof of concept only.** The glossary is injected whole into every question. With 10 entries that costs a few hundred tokens; with hundreds of entries it would not
   fit or would drown the question. At scale it has to be a retrieval step over vector embeddings (select the entries closest to the question, always keep the few that
   are global). That is step 4b; the spike with OpenRouter embeddings works. The `terms` field in the YAML is a stopgap for the same job.
2. **Every entry is an assumption.** The 10 entries are the author's defaults (`status: assumed`, owner "Maya (defaults until confirmed)"), not company answers. A real
   deployment has to let the company decide its own truths: what revenue means, what a new customer is, whether $0 orders count, what the fiscal calendar is. Those answers
   can differ from ours and would change the correct answer to the eval questions. The eval only measures that the pipeline uses a definition when one is given.
   The process around the file (who confirms, how a change is reviewed, how `assumed` becomes `confirmed`) is not built.

### Eval fix · q04 graded with zero tolerance (made after step 4a', author's call)

Reason: in 4a' q04 passed with 3.59, a rounded answer that happened to fall inside the 0.1% tolerance, so the pass did not show that the agent returns an exact
value when "exactly" is asked. The grader for q04 is now `rel_tol: 0, abs_tol: 0`: `numeric_value` must equal the gold, 3.592034445640474, and 3.59 or 3.6 fails.
- Changed: the grader tolerance of q04 only (and its comment). The question text, gold SQL, the $0-order assumption and the unit are unchanged. A unit test
  (`test_zero_tolerance_accepts_only_the_exact_value`) shows the exact value passes and 3.59 / 3.6 do not.
- This makes q04 stricter, not easier. Earlier results keep their verdicts (4a' passed q04 under the 0.1% tolerance; under this one it would have failed with 3.59).
  So 4a' is not comparable to the next run on q04: re-run the whole eval to compare (`step-04a3-q04-exact`, same agent and glossary as 4a').
- Expectation: the model rounds its answers by habit, so q04 probably fails again (17/20). If it passes, the wording "exactly" is enough. If it still fails, the lever is
  the answer-schema description for `numeric_value` ("unrounded, as returned by the query"), a generic change and its own step.

**Result** (run `step-04a3-q04-exact_questions_20261104-164447`, commit `2a487ad`; same agent, glossary and system prompt as 4a'):

Score: **17/20 = 85.0%** (4a': 18/20) · 0 errors · 10,822 tokens/run · 1.4 SQL calls/run. 1 run per question, not optimal.
- The only difference from 4a' is q04, as expected: the query returned 3.592034445640474 and the agent submitted `numeric_value` 3.59, which fails zero tolerance. "Exactly"
  in the question is not enough; the model rounds when it fills the answer field. Next candidate: say in the answer schema that `numeric_value` is the unrounded query result.
  That is a generic change (no question-specific rule) and would be its own step.
- **All 20 answers and all 20 token counts are identical to 4a'** (same inputs, temperature 0). Either the provider is deterministic for an identical request or the reply is cached;
  this run cannot tell which. Consequence: a re-run of an unchanged agent adds no information here, and the variance seen in earlier steps (q02, q06, q20 flipping) came from
  runs where the prompt or the context differed, or from provider behaviour at the time. Do not read "1 run" as a noisy sample of one fixed behaviour without checking this.
- Open: q04 (rounding), q16 (no query, invented figures), q19 (tax treated as a cost).

### Step 5 · A generated relationship map (hypothesis, written before the run)

Root cause targeted: the join graph is spread over the prompt (a `joins:` line in each table, a fan-out list at the end). The agent has to assemble it, and the
multi-hop case fails: in the last run q06 (perishable supply spend) summed `supplies.supply_cost` and never walked `supplies -> products -> order_items`. Nothing says
that supplies and orders connect only through products, or that `supply_cost` exists twice at different grains (`order_items` per item, `supplies` per supply row).

Change (generated from the manifest and the data, `agent/semantic.py`; no question-specific text, no new tools): a "Relationships" section before the table blocks with
(1) every join with cardinality and the count of child rows with no parent, checked in SQL; (2) the shortest join chain for every pair of tables with no direct join
(e.g. `orders <-> supplies`); (3) every non-key column name that exists in several tables, with the grain of each. The "Join risks" list is unchanged and already derived
from the same join list. Cost: about 1.5k characters more in the prompt.

Expected: q06 passes again and the multi-table questions (q10 q12 q13 q14) hold, perhaps with fewer SQL calls. q04, q16, q19 are not targeted. Prompt grows by
roughly 0.7k tokens/run. A fair result is 18/20 +/- 1; "no score change" is a real outcome and will be reported as that.

How it will be measured: the last runs showed that the same agent gives different replies on different days (q04, q06, q16 flipped with no change on our side). So the
comparison is **the 4a' agent and step 5 run back to back on the same day**, plus the holdout for both; a number from another day is not a baseline.

**Result** (runs `step-05-relationship-map_questions_20261105-141003` and `step-05-baseline-4a-sameday_questions_20261105-140959`, same minute, 1 run each; step commit `9d7151f`, baseline `0c424a4`):

| | 4a' same day | Step 5 |
|---|---|---|
| Score | **18/20 = 90%** | **16/20 = 80%** |
| tokens/run | 10,959 | 12,771 (+1.8k, +17%; predicted +0.7k) |
| SQL calls/run | 1.4 | 1.25 |

- **Hypothesis rejected.** Predicted q06 fixed and the rest holding; got q06 still failing and two new failures, q15 and q16.
- The baseline reproduced the earlier "step-04-final" run exactly (same verdicts, same 10,959 tokens/run), hours later. So the baseline is stable today and the 2-question gap is the step's effect on this run.
- **q06 still fails, with a different wrong answer.** It now joins to items but sums `order_items.supply_cost` for products that have a perishable supply: 131,788.38 (gold 104,719.19). That number equals the total `orders.order_cost` of all orders (seen in the q19 run), i.e. the cost of *all* supplies: the filter on perishable supplies
  selected products, not supplies, so every product with any perishable supply brought its whole cost. The path in the new section did not lead to the per-supply join that the question needs.
- **q15 and q16 regress to answering.** q15 returns an invented $1,234,567.89 with 0 SQL calls; q16 runs 2 queries and answers with a partial Q3 (-$66,204). The baseline asked for clarification on both. The cause is not known from one run; one reading is that a long section about joins pushes the glossary/period notes further from the question, but this was not tested.
- q19 still answers (3 SQL calls instead of 1). Token cost rose on most single-table questions (q01 +2.2k, q05 +2.2k, q06 +3.1k), i.e. the section is paid on every question, including those that never join.
- Not run: the holdout. The main set already says "no gain, a cost", so the holdout was not spent on it.
- Caveat: 1 run per side; q15/q16 flipped between days before without any change of ours, so the two flips are weaker evidence than q06 staying wrong. What is solid: **no gain on the targeted question, +17% tokens.**
- Reading the q06 logs again after the run: in the earlier passing runs the agent used the existing many-to-many warning ("aggregate each to one row per product_id first") and
  multiplied; in step 5 it took `order_items.supply_cost` instead. The new "same name, different grain, check which one you need" line is a plausible cause of that switch (not proven).
- Next options (not started): keep only the part that targets q06 (the shared-column line, 6 lines) and drop the 10-line path list; or put the relationships after the table blocks next to the join risks. Either is its own step and run with a same-day baseline.

### Step 5b · Measured fan-out in the join risks (hypothesis, written before the run; step 5 is kept in git history, its code is removed)

Research done first (web search, 2026-11-05). (a) SchemaGraphSQL (EACL 2026 findings) uses the foreign-key graph with path-finding to *select the few tables a question needs*, not to list every path. Step 5 listed every table pair, which is the opposite and cost +1.8k tokens/run. (b) M-Schema (XiYan-SQL) keeps the schema compact: types, keys, short descriptions, foreign keys in one place, sample values; self-reported by the authors and papers that build on it. (c) dbt Labs reports large gains from a semantic layer for questions it covers (vendor benchmark, 11 questions); that is the MetricFlow direction already planned, not a relationship-map change.

Change: no new section. The existing "Join risks" lines get the numbers the agent cannot see: the *measured* average rows per parent for each join, and for the many-to-many pair how many times each side would repeat (`order_items` x `supplies` through `products`: about 6.5 and 9090). Generated by `semantic.measure_fanout` (one count query per join) and printed by `edge_cases.join_risks`. Cost: about 100 tokens.

Hypothesis: a concrete multiplication factor makes the many-to-many warning harder to ignore than the words "inflated". Expected: q06 passes again (as in the runs that used the warning), q15/q16 are back to their baseline verdicts because the prompt is nearly unchanged in size, score 18/20 = same as the same-day baseline or +1, tokens +0.1k. If q06 still fails, a number in a warning is not what stops this error.

**Result 5b** (run `step-05b-measured-fanout_questions_20261105-144539`, 1 run, same day as the 4a' baseline): **18/20 = 90%**, 11,703 tokens/run (baseline 10,959; +0.7k, predicted +0.1k), 1.5 SQL/run.
q06 **passes** (3 SQL calls: aggregate supplies per product, multiply by the item count; the baseline's 15.81 fails today); q16 **fails** (0 SQL, figures stated for Q2 and partial Q3) where the baseline passes. Net 0.

**Controls: how much do cosmetic prompt changes move the score?** Two runs with no change in content, only the wording of one header (`Join risks (from the keys above):` -> `Join risks:`):
| Prompt | Score | q06 | q15 | q16 |
|---|---|---|---|---|
| 4a' baseline (header as before) | 18/20 | F | P | P |
| 4a' baseline, header renamed (`step-05c-control-A-header`) | **16/20** | F | P | F |
| 5b | 18/20 | **P** | P | F |
| 5b, header renamed (`step-05c-5b-with-header-rename`) | **14/20** | **F** | F | F |

- **A header rename with no content change moves the score by 2 questions (18 -> 16) and by 4 on 5b (18 -> 14).** At temperature 0 the same prompt is repeatable, but any change to the text (even a header) is a new draw. So a 1-run difference of 1 to 2 questions between two prompts is not evidence of anything, in either direction. This applies to every step so far (3d to 4a' included).
- q16 flips under a header rename alone, so its loss in 5b says nothing about the fan-out numbers. **q06's pass did not survive the header rename**, so 5b's fix is not shown to be robust either. Step 5 (-2) and 5b (0) are both inside this noise.
- Conclusion for 5b: **no demonstrated effect.** Not rejected (nothing shows it hurts), not accepted.

### Step 5c · Measurement fix: sampled repeats, same code, one switch (before trying more relationship ideas)
Since the prompt-level noise is as large as the effects tried, repeats at temperature 0 are useless (identical) and 1 run per prompt cannot decide. Change (no effect on the default): `AGENT_TEMPERATURE` (default 0) so `RUNS=3` gives three real samples, and `JOIN_FANOUT=off` to run the exact 4a' prompt from the same code (checked byte for byte against the `0c424a4` prompt: identical). Comparison: baseline (`off`) vs 5b (`on`), `AGENT_TEMPERATURE=0.5`, `RUNS=3`, same time. Decision rule fixed in advance: 5b counts as an improvement only if its mean score is higher by more than 1 question-equivalent (5 points) **and** q06's pass rate rises; otherwise the direction "text about relationships" is stopped.

**Result 5c** (runs `step-05c-T0.5-baseline-off_questions_20261105-145119` and `step-05c-T0.5-fanout-on_questions_20261105-145119`, temperature 0.5, 3 runs each, 60 records per arm):
| | 4a' prompt (`JOIN_FANOUT=off`) | 5b (`on`) |
|---|---|---|
| mean score | **83.3%** (runs: 18, 16, 16 of 20) | **81.7%** (runs: 18, 16, 15 of 20) |
| pass on all 3 runs | 75.0% | 75.0% |
| tokens/run | 11,921 | 11,390 |
| SQL calls/run | 1.6 | 1.4 |
- **Decision rule: not an improvement. The direction "more text about relationships" is stopped.** The gap (-1.7 points) is smaller than the spread between runs of one arm (2 questions = 10 points).
- **q06, the question the idea targeted, is identical in both arms: pass, pass, fail.** The measured fan-out numbers did not change it. And the plain 4a' prompt already passes q06 in 2 of 3 sampled runs, so there was little to gain on it: the single-run q06 failures of the last days were the unlucky draw.
- Per-question differences (all within noise): q15 3 of 3 pass in the baseline vs 0 of 3 in 5b (the only systematic-looking gap, one question, not explained); q20 2 of 3 vs 3 of 3; q04 0 of 3 vs 1 of 3.
- **What actually fails in the 4a' prompt at temperature 0.5 is not about joins:** q19 0/3 (invents a cost model for a question the data cannot answer), q04 0-1/3 (rounds), q16 1/3 (answers instead of stopping on a partial quarter). These are the next targets, and each is behaviour, not relationships.
- Kept from this step: the measurement switches (`AGENT_TEMPERATURE`, default 0, so nothing changes by default; `JOIN_FANOUT`, default on). The measured fan-out lines stay in the prompt only because they cost about 100 tokens and did no harm in the data; they are not a claimed improvement. Whether to keep them is the author's call (set the default to `off` to restore the exact 4a' prompt).
- Method lesson for every later step: compare prompts with `AGENT_TEMPERATURE=0.5 RUNS=3` (about 3 minutes, cheap) and judge the mean against the per-run spread; do not judge on one run at temperature 0.
