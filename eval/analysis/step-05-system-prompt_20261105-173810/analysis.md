# Step 5 · Professional system prompt: analysis

Runs (3 per question, same model `openai/gpt-oss-120b`, Cerebras, effort medium, same glossary and generated context):

| | baseline re-run (step-4 agent, today) | step 5 (new prompt) |
|---|---|---|
| result file | `step-05-baseline-rerun_questions_20261105-173527.json` | `step-05-system-prompt_questions_20261105-173810.json` |
| prompt sha | `ce5d3d1e7bb6` | `706909e61ef7` |
| mean score | 85.0% | **95.0%** |
| pass^3 | 80.0% | **95.0%** |
| tokens/run | 10,663 | 14,430 (+35%) |
| input / output tokens per run | 9.8k / 0.85k | 13.3k / 1.09k |
| errors | 0 | 0 |

Reference: `step-04-final` (3 runs, 2h earlier) scored 90.0%. The baseline was re-run because the same agent scored 85-90% on different days (provider drift), so the fair comparison is the same-day re-run: **+10 points (+2 questions)**.

## Research summary (what the prompt is based on)

- Anthropic prompting docs: be clear and direct; brief the model like a capable colleague without your context; give the reason behind a rule; tag sections with XML; put long reference data before the task and rules.
- OpenAI GPT-4.1 / harmony guides: agentic prompts need reminders to persist until done, to use tools instead of guessing, and to plan between tool calls; evaluate and iterate rather than trust the wording.
- Text-to-SQL practice: ground in the real schema, verify empty or odd results (does the filter value exist?), abstain or ask rather than guess, and enforce safety in code (this repo already has a SQL guard), not in the prompt.
- Caveat: most pages found were secondary summaries of the official docs; the principles were cross-checked between them, not read from the primary pages in full.

## What changed (only instruction text)

Tagged sections `<role>` `<warehouse>` `<workflow>` `<rules>`; a 5-step workflow (understand, check feasibility, query, verify, stop); rules for grounding ("no query, no number"), "use a column only for what its description says", when to ask, precision, efficiency; a recency reminder in the final-answer request; `numeric_value` described as unrounded.

## Per question

| change vs baseline | questions | reading |
|---|---|---|
| fixed (FFF to PPP) | q06, q19 | q06: baseline summed the whole `supplies` table (15.81); the new prompt's feasibility step ("use grain and join notes to avoid double counting") led to the right join 3/3. q19: baseline treated `tax_paid` as a cost; "use a column only for what its description says" made it decline 3/3 with 0 queries. |
| fixed (partly) | q04 (FPP to PPP), q15 (PFF to PPP) | q04: the unrounded rule held, 3.592034445640474 returned 3/3. q15: asks which period is meant 3/3. |
| **regressed** | **q16** (PPP to FFF) | see below |
| unchanged | the other 15 | all PPP before and after |

### q16 regression

Baseline passes q16 by answering with **0 queries**: it reads the generated note that Q3 holds only July and August and asks how to handle September. With the new prompt it runs 2 queries (Q2 revenue, Q3 revenue), then answers "-$66,204" with `assumptions: []` and status `answered`, 3/3 runs. The "no query, no number" rule worked as intended (the number is now grounded) but it also removed the path that made the model stop and ask: once it had queried, it treated the data note and the glossary rule `partial_periods` ("say so and ask before comparing") as already handled. So the same rule that fixed the invented figures of steps 4a/4a' exposes the real q16 problem: the model does not apply a partial-period concept to a comparison it computed itself. The earlier pass was a different failure mode that happened to look right.

## Cost: where the +35% tokens came from

Input tokens rose on every question by about 1k (the prompt is about 0.4k tokens larger, sent on 2-3 requests), and on four questions much more:

| question | SQL calls base to new | note |
|---|---|---|
| q10 | 1 to 6 | verify step: checks distinct locations, lists customer ids, re-ranks after the answer query already succeeded |
| q07 | 1 to 4 | extra sanity queries |
| q09, q11 | 1 to 3 | q09 repeats an identical query and re-counts the customers table "to check" |
| q12, q13 | 4 to 5, 6 to 7 | small |

So the "Verify before answering" step is the cost driver: it makes the model re-query things it already answered. Cheaper on q03 q14 q19 (fewer calls). Correctness was not harmed (all those still pass), but the verify wording is too broad.

## Conclusions

1. Hypothesis (+1 to +2 questions, no regressions, +0.3k to +1k tokens) was **partly met**: +2 net questions on the mean (+3 fixed, one regressed), pass^3 80 to 95; tokens +3.8k per run, more than predicted.
2. The gain came from two rules: "use a column only for what its description says" (q19) and the feasibility/grain step (q06). The structure and tags are not isolated: the change was made as one bundle, so which part of the rewrite matters is not measured (an ablation would be needed).
3. The grounding rule trades one failure for another on q16.
4. Caveat on honesty: the prompt was written after reading the step-4 failures; rules are generic and no eval wording or answers were used, but the holdout run (`make eval-holdout`) has not been done and is the check that this is not fit to the 20 questions. The eval is deterministic at temperature 0 on a fixed provider, so 3 runs mostly repeat one behaviour (in step 5 all three runs agreed on every question: pass^3 equals the mean) and say little about variance.

## Next (not done)

- 5b: narrow the verify step (verify only what the answer query did not already show; never repeat a query) and measure the token cost, expecting back to about 11-12k with the same score.
- 5c: partial periods at answer time: a `<rules>` line "when the question compares periods, check that both are complete in the data; if not, say so in assumptions and ask". Generic, but it is aimed at q16 by design, so it should be judged on the holdout.
- Holdout run for baseline and step 5.
