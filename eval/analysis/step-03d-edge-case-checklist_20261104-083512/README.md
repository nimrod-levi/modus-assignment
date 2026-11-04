# Step 3 wrap-up (3d: edge-case checklist), run `step-03d-edge-case-checklist_questions_20261104-083512`

Source: `eval/results/step-03d-edge-case-checklist_questions_20261104-083512.json`. Model `openai/gpt-oss-120b` via OpenRouter/Cerebras,
effort medium, commit `deffa23`, prompt sha `ce5d3d1e7bb6`. Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 15/20 = 75.0%. 0 errors, 0 rejected calls. 11,506 tokens/run, 2.0 SQL calls/run.**

> **This is 1 run per question, which is not optimal.** The author chose it to save tokens. Earlier steps showed single questions flipping
> between runs with unchanged logic (q02, q06, q20), so a one-question difference is inside the noise. Read the score as +/- 1-2 questions.

## Path through step 3 (same model, tools and questions)

| Sub-step | Change | Runs | Score | Tokens/run | Note |
|---|---|---|---|---|---|
| 2 (control) | compact schema, no context | 1 | 13/19 | 7,043 | 19 questions (q04 off) |
| 3 | generated structure: grain, keys, joins, descriptions, data facts | 1 | 10/20 = 50% | 10,191 | q04 on, q08 unit bug in the grader |
| 3b | + one refusal sentence in the prompt | 1 | 14/20 = 70% | 7,478 | |
| 3c | + hand-picked table notes | 3 | 66.7% mean, pass^3 65% | 8,670 | q08 unit bug still in the grader |
| **3d** | **fixed 11-check edge-case checklist instead of the notes** | **1** | **15/20 = 75%** | **11,506** | q08 grader fixed (`eac8bc8`) |

## What 3d changed, honestly

3d vs 3c on the same 20 questions: the only differences are q06 and q08, and neither is a checklist effect.
- **q08** passes because the grader now accepts the unit "drink items" (eval fix `eac8bc8`). The answer was always right. With the new unit list 3c
  would have scored about 71.7% (14.3/20), so the real step from 3c to 3d is about +3 points, one question, one run.
- **q06** passed this run; in 3c it passed 1 of 3 runs. Unstable, not fixed.
- **q17** (midnight timestamps) was fixed in 3c and stays fixed. The checklist reproduces that finding with a general check ("time of day").
- Everything else is unchanged: q03 q04 q15 q16 q19 fail exactly as before.

**So the checklist did not move the score. It did what we wanted for the approach:** the same useful finding now comes from a general
check that runs on every table, not from a sentence written for one failure. The score shows no loss from that swap, but no gain either.

## Cost

Input tokens per run: 3b 6.9k, 3c 8.0k, 3d 10.8k; output 0.6k, 0.7k, 0.7k. The 3d prompt carries a "Checked, nothing found" line per table,
the unit note and more findings, sent on every request. SQL calls per run went from 1.4 to 2.0. +33% tokens vs 3c, for no measured gain, is the
main argument against keeping the whole checklist output in every prompt (see "Next").

## What still fails and why (5 questions, none about structure)

| Question | What happens | Why generated context cannot fix it |
|---|---|---|
| q03 new customers | filters `customer_type = 'new'`, answers 0 (the real answer is 33) | A definition: "new" means first order in the month. The dbt description of `customer_type` points the other way. Glossary. |
| q04 days to second order | counts the 483 $0 orders | A customer assumption. Glossary. |
| q15 revenue last month | uses the data range to pick August 2025 and answers | There is no "today" in the data; only the user knows what it is. The prompt says to ask on ambiguity; the model does not treat this as ambiguous. |
| q16 Q3 vs Q2 | compares a two-month quarter with a three-month one | The finding "2025-Q3 has only Jul, Aug" is in the prompt; the model sometimes writes it as an assumption and answers anyway. This is a behaviour (and arguably a grader) question. |
| q19 net profit | revenue minus supply cost | Nothing in the data says other costs are missing. Needs the glossary or a list of absent concepts. |

The shared pattern: the data facts reach the model, and for q15/q16 it still answers. The next gains are definitions (q03 q04) and
behaviour when a period is partial or undefined (q15 q16 q19), not more data profiling.

## Caveats on the whole step

- The checklist was written after the step-3 failures. Time coverage and time of day are on it partly because we saw them fail; the other nine
  checks fired on nothing the eval tests (the cents note is the only extra finding). The approach is more general than the notes, but its
  effect on unseen questions is **not measured**. `make eval-holdout` has not been run for any step-3 variant.
- 3b and 3d are 1 run, 3c is 3 runs; the table mixes them. The 3b-at-3-runs baseline was never run.
- The refusal sentence (3b) was added after the failures it fixes (q18 q20).

## Next

1. Run `make eval-holdout STEP=step-03d-edge-case-checklist`: the only test here on questions nobody tuned against.
2. Glossary step (separate, labelled file): definition of new customer, $0 orders, what "today" is, which costs exist. Targets q03 q04 q15 q19.
3. Decide whether the "Checked, nothing found" lines earn their tokens: try the checklist with findings only and compare tokens and score at `RUNS=3`.
4. Then the dbt metrics (MetricFlow) tool.
