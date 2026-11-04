# Step 3 analysis (generated structural context), run `step-03-structural-context_questions_20261104-080457`

Source: `eval/results/step-03-structural-context_questions_20261104-080457.json`. Same model, provider, reasoning effort and tools as
steps 1-2; 1 run per question; prompt sha `58b4a33c809d`; commit `a7ddb3e` (dirty tree). Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 10/20 = 50.0%. 0 API errors, 0 rejected calls. Tokens/Q 10,191 (step 2: 7,043). SQL calls/Q 2.45 (step 2: 2.53).**

## Verdict: the hypothesis did not hold

The prediction was +1 to +3 questions over step 2 and about +1-2k tokens/Q. Result: **-3 on the 19 questions both runs share (13/19 to 10/19)**
and +3.1k tokens/Q (input 6,194 to 9,356; output unchanged at about 840).

| | Step 1 | Step 2 | Step 3 |
|---|---|---|---|
| Score (common 19, q04 excluded) | 13/19 | 13/19 | 10/19 |
| Score (reported) | 13/19 | 13/19 | 10/20 (q04 back, fails) |
| Tokens/Q | 19,090* | 7,043 | 10,191 |

*Step 1 and 2 numbers are from the scoreboard; use step 2 vs step 3 for the token comparison.

Predictions checked:
- q11 q12 (stores without orders): already passed in steps 1-2, so no gain was possible. Still pass.
- q15 (data range): **not fixed, and the fact made it worse in kind.** The agent now writes "August 2025 based on the data range" and answers confidently.
- q01/q02 (tax in the description): q01 passes as before. q02 flipped to pass, but it went pass, fail, pass across steps 1-3, so treat it as unstable, not as a gain.
- Grain questions should "hold": **q06 regressed** (see below).
- q04, q17-q20: not expected to move; they did not.

## What changed (compared with step 2)

| Flip | Question | Cause | Is it the context? |
|---|---|---|---|
| P to F | q06 perishable supply cost | Joined `order_items` to `supplies` on `product_id`, then summed `order_items.supply_cost`: 396,061 vs 104,719 (3.8x over). | **Yes, a generator gap.** The warning I generate only says that *parent* columns over-count. Here the fan-out is between two tables that share a key (`order_items` and `supplies` both point at `products`), and the summed column is already a per-item total. The prompt had the warning and the model still fell into the trap. |
| P to F | q03 new customers Jan 2025 | Filtered `customer_type = 'new'` (0 rows), saw 33 in the next query, and answered 0. | **Probably.** In steps 1-2 the prompt had no descriptions and q03 passed. The dbt description says 'new' means "has only placed their first order to date", and the model used it literally. Not proven with one run. |
| P to F | q08 drinks sold | Answer 70,819 is correct. The grader rejected the unit "drink items" (allowed: drinks, items). | **No.** A grader strictness issue. Changing the unit list is an eval fix for the author to decide; I did not touch it. |
| F to P | q02 | Passed in step 1, failed in step 2, passes again: unstable across three runs of unchanged logic. | No (variance). |
| P to F | q20 | Passed only in step 2; failed in steps 1 and 3. | No (variance). |

So at most two of the flips (q06, maybe q03) can be blamed on the context. The rest are run-to-run noise at 1 run per question and a unit
grader. **This run cannot say whether step 3 is better or worse than step 2.** It does say the generated context did not help the
unanswerable and time questions, and that it cost 45% more tokens.

## What still fails and why (q15-q20 + q04)

- **The structural context describes what exists; the failures are about what does not exist or is not allowed.** q17 shows it best:
  the agent discovered that every timestamp is midnight (5 SQL calls) and still answered "hour 0 is busiest". No generated fact
  said "ordered_at has no time of day", and no rule said to decline.
- **q18, q19, q20:** the agent invents a proxy (refund = $0 order, cost = supplies only, target = $100,000). Nothing in the prompt
  says "if no column holds the concept, say so".
- **q15, q16:** the date range is now in the prompt and the agent uses it to justify a guess. The question needs a rule about what "today" means.
- **q04:** needs the customer's $0-order assumption (glossary).

## Cost

Prompt grew from about 1k to about 1.5k tokens, sent on every request (3 per question), which explains +3.1k input tokens/Q. The
descriptions and ranges for every column are included whether the question needs them or not. Latency is about the same (median 2.1 s).

## What I would do next (in this order)

1. **Re-measure before changing anything:** run step 2 on the 20 questions and step 3 with `RUNS=3`. One run per question cannot separate a
   -3 from noise; q02 and q20 already flipped in both directions across steps 1-3.
2. **Fix the generator gaps seen here** (still generated, none typed by hand): warn when two tables join the same key (sibling fan-out),
   say when a column is already a per-row total, and add data facts for "time of day is always midnight" and "months present per quarter".
   Test whether dropping column descriptions that only restate names removes the q03-style regression and some tokens.
3. **Add the refusal rule as its own step:** a generic prompt rule ("if no table or column holds the concept asked for, answer
   `cannot_answer` instead of using a proxy; if the date is relative, ask") targets q15 q17-q20. It is a rule about behaviour, not about
   a question, so it fits CLAUDE.md. Keep it a separate step so its effect is measured alone.
4. **Decide the q08 unit list** (author's call, logged as an eval fix if changed).
5. Then step 4 (metric definitions via MetricFlow), then the glossary for q03/q04.
