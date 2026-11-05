# Holdout 1 (h01-h10): analysis

Run `holdout-01_holdout_20261105-180438.json`, **1 run per question** (the `eval-holdout` Makefile target does not forward `RUNS`), agent = step 5 (prompt sha `706909e61ef7`, `openai/gpt-oss-120b`, Cerebras, effort medium).
The questions were written after the step-5 agent was built, not tuned on it, and this is the first and only run.

Score: **8/10 = 80%** as run; **9/10 = 90%** after the set-grader eval fix (h06, see STEPS.md; re-graded file `holdout-01_holdout_20261105-180438_regraded.json`) · 0 errors · 14,245 tokens/run · 1.9 SQL calls/run. Step-5 dev set for reference: 95% (3 runs). Hypothesis in STEPS.md was 5-7 of 10; the agent did better than predicted.

| id | result | SQL calls | tokens | what happened |
|---|---|---|---|---|
| h01 weekday avg daily revenue | P | 2 | 15.3k | Averaged per date (1928.08), answered Friday; did not fall for the 53-Sundays total, did not refuse for "no hour of day" |
| h02 avg order value | P | 1 | 10.4k | Applied the `$0` rule (10.3708, not 10.2900) |
| h03 food share % | P | 3 | 18.8k | Item level, percent not fraction; cited `[empty_orders]` (harmless, item sums are unaffected) |
| h04 top total gross profit | P | 1 | 12.0k | Pourover, $88,528.50; not the per-unit leader |
| h05 pourover units | P | 4 | 21.0k | Found the trailing space after the first query returned nothing; 14,325 |
| h06 highest tax rate store | **F (grader)** | 1 | 10.0k | Answered "Los Angeles ... 0.08 (8%)" correctly. The model wrote U+202F (narrow no-break space) between the words, so `_contains_word` does not match "Los Angeles" |
| h07 Q1 2025 minus Q4 2024 | P | 2 | 15.2k | Answered $63,130 with no clarification: the partial-period rule did not over-trigger |
| h08 avg first-order spend | P | 1 | 10.8k | Ranked positive orders itself (14.9893, not 14.8952) |
| h09 top supplier | **F (agent)** | 4 | 21.8k | Answered "lamb and pork bratwurst, $2.34", status `answered` |
| h10 YoY for Aug 2025 | P | 0 | 7.2k | `cannot_answer` from the data note alone, no query |

## Findings

1. **h09 is the one real failure, and it is the predicted loophole.** `supplies.supply_name` (an ingredient such as "banana") was read as the supplier. It also summed `supply_cost` over the 65 per-unit supply rows (one unit of each), so $2.34 is not spend on anything sold. The step-5 rule "use a column only for what its description says" did not hold here, even though the same rule fixed q19: `supply_name` has no description to contradict, and "supplier" sounds close enough to "supply". The model also ran 4 queries (a re-run of the same query with a different LIMIT), and the step-5 prompt has no rule against re-running a query with a different LIMIT (a narrower "verify" wording was planned, not done).
2. **h06 is an eval defect, not an agent defect.** The answer is right. The set grader lowercases and regex-matches the whole word, but does not normalise Unicode whitespace; U+202F, U+00A0 and the non-breaking hyphen (U+2011, seen in "pre‑tax" in the same answers) are produced by this model. Corrected score would be 9/10. This affects every `set` question with a multi-word gold (q13 is one word, h04 passed only because the model wrote plain spaces). Per CLAUDE.md the fix must be its own "eval fix" commit with the reason logged; it was made afterwards in its own commit (9/10).
3. **The traps that were expected to break the agent mostly did not.** h01, h02, h03, h04, h05, h07 and h08 passed, including the three that needed the glossary's `$0`-order rule (h02, h08) and the item-vs-order grain (h03). The step-5 prompt and glossary generalise to these concepts.
4. **Passing is partly lucky on one question.** h03 cited the `$0` rule for an item-level query where it is irrelevant, and h04 added the same assumption. Harmless to the numbers, but it shows the glossary rule is applied by keyword, not by reasoning about whether it matters.
5. **Cost.** 14.2k tokens/run, same as the dev set (14.4k). h05 and h09 (4 calls each) are the expensive ones; h10 answered with 0 queries.

## Caveats

- One run per question: a pass or fail here can flip (steps 4-5 showed run-to-run and day-to-day drift of 5-10 points). Treat 8/10 as 7-9.
- Four of the ten (h02, h03, h07, h08) depend on assumed glossary rules; h10 accepts only `cannot_answer`.
- The holdout is now partly seen: the h06/h09 failures are known. Further changes to the agent should not be tuned on them; new holdout questions would be needed to measure a fix.

## Next (not done)

1. ~~Eval fix: normalise Unicode whitespace/hyphens in `_contains_word`, then re-grade this result file.~~ Done (see STEPS.md): 9/10.
2. ~~Make `eval-holdout` forward `RUNS`~~ (done); re-run with 3 runs (not done).
3. h09 is a context problem (no supplier concept in the glossary or generated notes); any fix must be generic, e.g. a check that a named entity in the question ("supplier") has a column, not a rule about suppliers.
