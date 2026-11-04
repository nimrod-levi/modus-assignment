# Step 4a: customer glossary, all entries sent with the question. Run `step-04a-glossary-all_questions_20261104-095159`

Source: `eval/results/step-04a-glossary-all_questions_20261104-095159.json`. Model `openai/gpt-oss-120b` via OpenRouter/Cerebras, effort medium,
commit `a865982`, system prompt sha `ce5d3d1e7bb6` (identical to 3d: the glossary is in the user message, so the system prompt did not change).
Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 16/20 = 80.0% (3d: 15/20 = 75.0%). 0 errors, 0 rejected calls. 10,191 tokens/run (3d: 11,506), 1.1 SQL calls/run (3d: 2.0).**

> **1 run per question, which is not optimal.** One question is inside the noise (single questions flipped between runs in earlier steps).
> The +1 below is q03, the question the `new_customer` entry was written for.

## What the step changed

`glossary/glossary.yaml`: 10 entries, the author's defaults until the customer (Maya) confirms them. All are `assumed`. They are validated against
the warehouse by `make glossary-check` and sent after the question in the first user message. What the warehouse lacks (refunds, targets, costs
other than supplies, order times) is deliberately not listed; the agent has to find that out itself.

## Result against the hypothesis

| Hypothesis (STEPS.md) | Result |
|---|---|
| 17/20: q03 and q04 fixed, q19 unchanged | **16/20.** q03 fixed. q04 not fixed, for a rounding reason (below). q19 unchanged. |
| q15 q16 may improve because the glossary says to ask | **No.** Both still answer, and now without a query. |
| No regression on q01 q09 q13 q14 (the `empty_orders` risk) | **Held.** All 15 questions that passed in 3d pass again. q09 = 935, q13 = Brooklyn. |
| Tokens +0.4k to +0.8k per question | Median **+0.8k**, as predicted. The mean fell by 11%, but that is not a saving (see Cost). |

## Question by question (what changed from 3d)

| Question | 3d | 4a | What happened |
|---|---|---|---|
| q03 new customers | F | **P** | 33, equal to gold. The assumptions cite `[new_customer]` and `[empty_orders]`. The definition fixed the definition error. |
| q04 days to 2nd order | F | F | The agent applied the $0-order rule. The query returned 3.592034..., the agent submitted `numeric_value` 3.6. That is 0.25% off against a 0.1% tolerance. **The logic is right; the number was rounded.** |
| q15 revenue last month | F | F | Reads `relative_dates`, states the data end date, picks July 2025 and answers. **0 SQL calls; the figure ($1,234,567.89) is invented.** 3d queried and answered August with a real figure. |
| q16 Q3 vs Q2 | F | F | Says Q3 is incomplete (July and August) and answers anyway. **0 SQL calls; Q2 $1,842,560, Q3 $1,219,340 and the $623k drop are invented.** 3d queried (-$66k). |
| q19 net profit margin | F | F | Not in the glossary, as decided. **0 SQL calls**, invents a "tax paid" cost, answers 13.2%. 3d queried and answered 80.4% (also wrong). |
| the other 15 | P | P | Unchanged. |

## The new failure: answers with no query

Three failures went from "wrong definition on real data" to "figures nobody computed". This matters more than the score: in the CFO scenario
(Part 2 of the task) an unqueried number is worse than a wrong definition, because nothing in the trace can show where it came from.
- It happens exactly on the three questions where the glossary says to ask or to state a limit (q15, q16) or where the concept is missing (q19).
  On every question the glossary answers directly, the agent still queries (1 to 4 SQL calls).
- In q15 and q16 the model read the relevant entry (it quotes the data end date and the incomplete quarter) and treated it as enough to answer.
  Reading "state the data end date" seems to have been taken as a licence to answer. This is a hypothesis; it is one run.
- Not caused by a prompt change: the system prompt sha is identical to 3d. The only difference is the glossary block in the user message.
- To test: run `RUNS=3` on q15 q16 q19 (`make eval STEP=step-04a-glossary-all ONLY=q15,q16,q19 RUNS=3`) and look at the SQL call count.

## Cost

| | 3d | 4a |
|---|---|---|
| tokens/run | 11,506 | 10,191 |
| input / output per run | 10,779 / 727 | 9,317 / 874 |
| SQL calls/run | 2.0 | 1.1 |
| median change per question | | **+0.8k** |

The mean fell because of single-run swings: q07 26k to 14k and q13 39k to 14k (fewer SQL calls) and q15 q16 q19 down 3k to 4k each (no query at all).
On a typical question the glossary costs tokens: the block (about 500 tokens) is read on each request, and the answers are longer (+147 output
tokens/run) because the revenue entry asks for the definition to be stated. Do not read the mean as a saving.

## What still fails (4 questions)

| Question | Kind | Next |
|---|---|---|
| q04 | rounding of `numeric_value` | eval fix (separate commit): the question now asks for the exact value, to see that the agent does not round |
| q15 q16 | behaviour: ask instead of answering, and do not answer without a query | check stability at RUNS=3 first; a generic "figures must come from a query" rule would be its own step |
| q19 | missing concept, found by the agent itself | same no-query problem; not in the glossary by design |

## Caveats

- 1 run per question. q15 q16 q19 may differ on another run; that is why a RUNS=3 look at those three comes before any fix.
- The glossary entries are the author's assumptions, not customer answers. Several (new customer, empty orders, relative dates, partial periods) match questions
  that failed, so q03 is not evidence the agent finds such gaps itself. The holdout run is the fair test and has not been run for 3d or 4a.
- All entries are `assumed`. A confirmed entry may say something else (for example a real "today"), which would change the right answer to q15.
