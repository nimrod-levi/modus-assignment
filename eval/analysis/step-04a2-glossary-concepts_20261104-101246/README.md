# Step 4a': the glossary holds concepts only. Run `step-04a2-glossary-concepts_questions_20261104-101246`

Source: `eval/results/step-04a2-glossary-concepts_questions_20261104-101246.json`. Model `openai/gpt-oss-120b` via OpenRouter/Cerebras, effort medium,
commit `ce6f329`, system prompt sha `ce5d3d1e7bb6` (same as 3d and 4a). Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 18/20 = 90.0% (4a: 16/20, 3d: 15/20). 0 errors, 0 rejected calls. 10,822 tokens/run (4a: 10,191; 3d: 11,506), 1.4 SQL calls/run.**

> **1 run per question, which is not optimal.** Single questions flipped between runs in earlier steps, so read this as +/- 1-2 questions.
> **The 4a to 4a' comparison is not clean: q04's wording changed in between** (eval fix `610ecb8`, the question now says "exactly"). On the 19 other
> questions the step is **17/19 vs 16/19, +1 (q15)**.

## What the step changed

The glossary lost every date, name and example (`relative_dates`, `partial_periods`, `store_start_date`, `customer_identity`): it says what a word
means, and the data facts (last date, partial quarter) come from the generated context. The question for this run: does the agent still ask for
clarification when the concept is in the glossary and the facts are in the generated notes?

## Question by question (changes from 4a)

| Question | 4a | 4a' | What happened |
|---|---|---|---|
| q04 days to 2nd order | F | **P** | Passes with the new wording. The rule is applied, the answer is **3.59 (rounded to 2 decimals)**. It passes because 3.59 is 0.057% from 3.592034, inside the 0.1% tolerance. The agent did not return the exact value, so this does not show it understood "exactly". |
| q15 revenue last month | F | **P** | `needs_clarification`: asks which month, and states that the last date in the data is 2025-08-31. 0 SQL calls, no figure given. The date came from the generated ranges, not from the glossary, which no longer contains it. |
| q16 Q3 vs Q2 | F | F | Says Q3 has only July and August, answers anyway, **0 SQL calls, invented numbers** (Q2 $1,234,567, Q3 $890,123, -27.9%). In 4a other figures were invented. The same failure in 2 of 2 glossary runs. |
| q19 net profit margin | F | F | Now queries (4 calls) but subtracts the supply cost **and `tax_paid`** and calls it net profit: 73.99%. Costs that are not in the data are not listed anywhere, by design. |
| q03 new customers | P | P | 33, correct; 2 SQL calls (1 in 4a), 12.8k tokens. |
| the other 15 | P | P | Unchanged. |

## What this shows, and what it does not

- **Concepts-only did not hurt.** Removing the dates did not lose q03, and q15 got better: the agent combined "a relative period needs a question" (glossary) with
  "the data's last date" (generated notes). That is the split we wanted. One run: q15 could flip back.
- **q04 is a hint effect, not an understanding effect.** The answer is still rounded. The fix is accepted by the tolerance, not earned. If the tolerance
  were 0.01%, it would fail.
- **q16 is the real open problem.** It makes no query and invents figures in both glossary runs, while the same entry makes q15 ask correctly. The agent states the
  partial quarter as a caveat and answers; the caveat is not a stop. A "figures must come from a query" rule would be a separate step.
- **q19 moved from "no query" to "wrong cost model".** With a query the model treats tax as a cost. The data cannot say that labour or rent are missing.

## Cost

| | 3d | 4a | 4a' |
|---|---|---|---|
| tokens/run | 11,506 | 10,191 | 10,822 |
| input / output per run | 10,779 / 727 | 9,317 / 874 | 9,900 / 922 |
| SQL calls/run | 2.0 | 1.1 | 1.4 |

The median per-question change from 4a is -57 tokens: the cost sits in the few questions that used more calls (q03, q07, q10, q13, q14, q19 at 2 to 4 calls)
and not in the glossary text. The glossary block is the same size or smaller than in 4a.

## Caveats

- Every entry is an author's assumption, not a company truth (see the note in STEPS.md). The score says the pipeline works when the definitions are what the
  questions assume. It does not say the definitions are right for any company.
- The glossary is injected whole. With 10 entries that is cheap; it does not scale (see the note in STEPS.md: embedding retrieval is the next step).
- Entries were written with the failed questions in view (new customer, empty orders, relative dates, partial periods), so the score is not evidence of finding gaps.
  The holdout run (`make eval-holdout`) has not been done for 3d, 4a or 4a'.

## Next

1. Decide what to do with q16 (and q19): check with `RUNS=3` on `ONLY=q16,q19` that they are stable, then a separate step for "figures must come from a query".
2. Step 4b: embedding retrieval of glossary entries.
3. Holdout runs for 3d and 4a'.
