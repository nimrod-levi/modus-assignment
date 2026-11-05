# Step 4 final: the 4a' agent, run 3 times. Run `step-04-final_questions_20261105-135451`

Source: `eval/results/step-04-final_questions_20261105-135451.json`. Model `openai/gpt-oss-120b` via OpenRouter/Cerebras, effort medium, commit `0c424a4`
(`agent/` and `glossary/` are unchanged since `2a487ad`; the only later code change is `agent/web.py`), system prompt sha `ce5d3d1e7bb6`
(same as 3d, 4a, 4a', 4a3). Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 18/20 = 90.0% (3 runs per question, pass_all 90.0%). 0 errors, 0 rejected calls. 10,959 tokens/run, 1.4 SQL calls/run.**
Last scored run, 4a3 (same agent, 1 run): 17/20 = 85.0%.

## The headline needs a caveat: the three runs are one sample

All 60 records (20 questions x 3 runs) give the **same verdict per question and the same input/output tokens per question**. Per-question scores are only 0.0 or 1.0.
Latencies differ between the runs (q01: 2.4 s, 1.6 s, 2.2 s), so the replies were not served from a cache: the provider is deterministic for an identical request
within a session. Consequence: **3 runs here are not 3 independent samples; the confidence is that of 1 run.** "pass_all = 90%" only means the same 18 questions passed every time.

## Same agent as 4a3, different result: the provider changed, not the code

`git diff 2a487ad HEAD` over `agent/`, `glossary/` shows only the new `agent/web.py`; the system prompt hash is identical. Yet against the 4a3 run (a day earlier):

- **0 of 20 answers are identical** (wording, SQL or numbers differ), and 3 verdicts flipped (table below).
- Mean tokens per run barely moved (9,900 + 922 -> 10,036 + 923 input/output), but per question they moved a lot: q07 17.5k -> 10.2k, q10 15.6k -> 9.4k, q19 19.4k -> 9.8k,
  q13 18.7k -> 26.0k, q18 5.9k -> 11.9k (now 2 SQL calls where it made 0).

This **corrects the 4a3 update**, which concluded that an identical request gives an identical reply and that "a re-run of an unchanged agent adds no information".
That holds inside one session only. Across days the same request gave a different reply for every question. Likely causes (not verifiable from the logs): the
Cerebras-served model or serving stack changed, or OpenRouter routed differently. The logs store the provider name but no model build or response id.
Meaning for the scoreboard: **a score measures (agent + provider on that day)**. The "+/- 1-2 questions" caveat is real after all; it applies to re-running the
same agent on another day, not to repeating it within one.

## Question by question (changes from 4a3)

| Question | 4a3 | final | What happened |
|---|---|---|---|
| q04 days to 2nd order | F | **P** | Returns the unrounded 3.592034445640474. The same prompt that rounded to 3.59 a day earlier keeps the digits now. Nothing in the agent explains it. |
| q16 Q3 vs Q2 | F | **P** | `needs_clarification`: Q3 is incomplete (data ends 2025-08-31), asks how to handle September. 0 SQL calls, no figures. In 4a and 4a' the agent invented numbers here. |
| q06 perishable supply spend | P | **F** | **Regression.** `SELECT SUM(supply_cost) FROM supplies WHERE is_perishable_supply` = $15.81; never joined to `order_items`, so it reports the unit cost of the supply catalogue, not spend. Gold 104,719.19. 4a3 joined and passed. This is the supplies fan-out/grain trap; q06 has flipped in steps 1, 3 and now 4. |
| q19 net profit margin | F | F | Still answers where gold is `cannot_answer`: 79.35% = (subtotal - `order_cost`) / subtotal. 1 SQL call (4a3: 4 calls, 73.99%, tax treated as a cost). A different cost model, still invented: the data has no labour, rent or overhead and the agent does not say so. |
| the other 16 | P | P | Verdicts unchanged, though every answer text differs. q12/q13/q14 use more SQL calls (4/5/3 vs 2/3/2); q18 and q20 now query (2 and 1 calls) before declining. |

## Results by category

| Category | Score |
|---|---|
| metric-definition (q01-q04) | 4/4 |
| units (q05) | 1/1 |
| grain (q06-q10) | 4/5 (q06) |
| entity (q11-q13) | 3/3 |
| time (q14-q16) | 3/3 |
| unanswerable (q17-q20) | 3/4 (q19) |

## Path so far (zero-tolerance q04 from 4a3 on)

| Step | Score | Tokens/run | SQL/run | Runs |
|---|---|---|---|---|
| 3d edge-case checklist | 15/20 (75%) | 11,506 | 2.0 | 1 |
| 4a glossary (all) | 16/20 (80%) | 10,191 | 1.1 | 1 |
| 4a' glossary concepts only | 17/20 (85%) | 10,822 | 1.4 | 1 |
| 4 final (other day) | **18/20 (90%)** | 10,959 | 1.4 | 3 (identical) |

Note: 4a' is shown at 17/20 (zero-tolerance q04), as in the 4a3 re-grade. The 3d to 4a' gain (+2) comes from the glossary, measured on one provider day; the last +1 is a
provider-day difference (q04 +, q16 +, q06 -), not an agent change. Do not present 90% as "the glossary got better"; present 85% to 90% as the range of the same agent.

## What this shows, and what it does not

- **Stable in both measurements:** q15 and q17 pass, q01-q03, q05, q07-q11 pass, q19 fails. These are the findings to trust.
- **Unstable across days:** q04 (rounding), q06 (join to items), q16 (stop vs answer). Each flipped with no change on our side. They sit where the agent depends on a
  habit rather than a rule: keep unrounded digits, join to items for spend, stop when a period is partial.
- **q19 is the one persistent failure.** It fails in all four glossary-era runs with a different wrong cost model each time. Nothing generated says that net profit
  needs costs this warehouse does not hold.
- The glossary fixes definition questions (q03, q15) durably; it does not remove variation in habit-dependent ones.

## Caveats

- Every glossary entry is an author's assumption (see STEPS.md). The score says the pipeline works when definitions match the questions.
- Entries were written with the failed questions in view, so this is not evidence of finding gaps. The holdout (`make eval-holdout`) has still not been run for
  3d, 4a or 4a'; it is now the most useful next number, more than more repeats of the main set.
- The glossary is injected whole; it does not scale (4b: embedding retrieval).

## Next

1. Run the holdout on the current agent and on 3d, back to back on the same day, so provider variation does not sit between the two.
2. Compare steps only from runs made together; do not compare a fresh run with a number from another day.
3. Candidates for separate steps: "`numeric_value` is the unrounded query result" (q04), a generic fan-out/spend rule or a MetricFlow metric (q06), an
   unanswerable-metric check (q19).
4. Store a response/model id per call in the result file so a provider-side change is visible in the log.
