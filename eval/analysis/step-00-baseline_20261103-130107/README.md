# Step 0 baseline analysis, run `step-00-baseline_questions_20261103-130107`

Source: `eval/results/step-00-baseline_questions_20261103-130107.json`
Model `openai/gpt-oss-120b` on Groq, 1 run per question, git `df52ed8` (dirty), prompt sha `c0470d807604`.
Eval set after the q01/q04 fix. Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 7/20 = 35%. The harness marked the run INVALID: 8 questions crashed and it did not write to the scoreboard.**

| Outcome | Questions |
|---|---|
| Pass (7) | q01 q03 q05 q07 q09 q13 q14 |
| Wrong answer, ran to the end (5) | q02 q16 q17 q18 q19 |
| Crash on a rejected tool call (8) | q04 q06 q08 q10 q11 q12 q15 q20 |

Per category: units 100%, metric-definition 50%, grain 40%, entity 33%, time 33%, unanswerable 0%.

## 1. The crashes: 8 of 20 questions never submitted an answer

Groq returned a 400 `tool_use_failed` for each. Four patterns:

| Pattern | Questions |
|---|---|
| Called a tool that doesn't exist (`json`) | q04 q06 q10 q15 |
| Wrote prose or markdown where the tool arguments belong | q08 q20 |
| Malformed tool name (`name=submit_answer`) | q11 |
| Called `run_sql` on the last turn, when only `submit_answer` is allowed | q12 |

These are infrastructure failures: the model did the reasoning and then could not hand the answer over.
Reading the intended answers in `failed_generation`:

- **Likely correct:** q08 (70,819), q10 (0), q11 (2). q12 probably too: the earlier run reasoned its way to 0.
- **Would still fail:** q04 (3.52 vs the new gold 3.592, because its SQL does not ignore $0 orders), q06 (396,061 vs 104,719, a double count), q15 (answered with $0), q20 (asks for a target instead of `cannot_answer`).

So without crashes this run would be about 10 or 11 of 20, not 7.

## 2. Wrong answers and what is behind them

| Root cause | Questions | What happened | What a fix has to supply |
|---|---|---|---|
| **Join fan-out / grain** | q02 (and q06 behind its crash) | q02 summed `orders.subtotal` after joining to `order_items`, so each order's subtotal is counted once per item. `orders` already has `order_cost`. q06 summed `order_items.supply_cost` (already the total per item) after joining `supplies` again. | dbt docs: grain of each model, what each cost column already contains. |
| **Answers when there is no data** | q17 q18 q19 (q20 behind its crash) | q17 took the hour of midnight-only timestamps. q18 saw no negative totals and said 0%. q19 called revenue minus supplies "net profit" and counted tax as revenue. An empty or flat result is treated as an answer. | Data facts (no time of day, no refunds, no targets, only supply costs) and an explicit "return `cannot_answer` when the warehouse cannot support the question" rule. |
| **Time window** | q16 (q15 behind its crash) | Q3 2025 has only July and August, but was compared with a full Q2. "Last month" was read as Oct 2026, where there are no orders. | Generated profile facts (min and max date, months present per quarter) and a clarification rule. |
| **Customer definitions** | q04 | "First and second order" counts $0 orders unless told otherwise (the gold now ignores them). | Glossary file with the customer's definitions, kept separate and clearly labelled. |

## 3. What passed

- q01 passes because the question now states "including sales tax". It no longer tests whether the agent picks pre-tax revenue.
- q03 q05 q07 q09 q13 q14 are straightforward from the schema names.
- q14 passed here and crashed in the first run, which shows the crashes are random per run.

## 4. Comparison with the earlier (deleted) run

The score is the same, 35%, but the pattern is not:

- Always failing in both runs: q02 q16 q17 q18 q19.
- Crashed in both: q04 q06 q10 q12 q20.
- Crashed only this run: q08 q11 q15.
- Crashed only before: q14 (passes now).

The same score came from different questions. This is why the infra noise has to go before step 1: otherwise a gain or loss at step 1 could just be Groq's behaviour on that day.

## 5. Open decision (not done yet)

The harness refuses to record this run. Options:

1. **Harness fix as its own commit, then re-run step 0.** Return a rejected tool call to the model as an error and let it retry. Also reconsider forcing `submit_answer` on the last turn (q12). It touches the baseline agent, which CLAUDE.md says not to change, so it needs your call.
2. **Keep the baseline as is.** Tag it at 35% and list the 8 crashes as a known weakness. The scoreboard would need `--allow-errors` or similar.

## 6. Planned order for the fixes (for discussion)

1. Harness fix and a clean step 0.
2. dbt docs (column meaning, grain): targets q02 q06.
3. Glossary (customer definitions): targets q04 q19.
4. Data profile facts and abstain rules: targets q15 q16 q17 q18 q19 q20.

Fix steps must be general root causes, with no question-specific prompt rules.
