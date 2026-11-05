# Explored directions that did not lead to implementation (2026-11-05)

**Status: documentation only. This branch (`worktree-step-05-relationship-map`) is not to be merged into the agent.** The agent on `main` (4a', commit `0c424a4`) is unchanged. The code on this
branch exists so the experiments can be reproduced; the full per-step write-ups are in `STEPS.md` (Steps 5, 5b, 5c, 6a, 6a') and the AI-assistance notes in `AI_USAGE.md`.

Goal of both directions: make the connections between tables clearer to the agent, then use the company's own MetricFlow definitions, without changing the model or the database.

## What was tried and what it showed

| Direction | Change (all generated from the manifest and the warehouse) | Result | Verdict |
|---|---|---|---|
| **5. Relationship map** | A "Relationships" section: every join with cardinality and orphan count, the shortest join chain for every table pair with no direct join, columns with the same name in several tables. | 16/20 vs 18/20 for the unchanged agent the same day; +1.8k tokens/run (+17%); q06 (the targeted question) still failed; q15 and q16 regressed. | Rejected. |
| **5b. Measured fan-out** | No new section: the existing "Join risks" lines gained measured rows-per-parent (e.g. 6.5 `supplies` per product; 9,090 `order_items` per product). | One run: 18/20, q06 fixed, q16 lost. After a cosmetic header rename the same prompt scored 14/20 and q06 failed again. At temperature 0.5, 3 runs: 81.7% vs 83.3% for the plain prompt. | No effect. |
| **6a. Metric catalog** | The 19 dbt/MetricFlow metrics as one line each (name, type, description, the SQL they imply), from `manifest.json`. | 3 runs, temperature 0.5, same time: 76.7% vs 75.0% without (+1.7 points; bar set in advance was +5). q18 and q20 declined more reliably (a lead). | No effect beyond noise. |
| **6a'. Closed catalog** | The same, plus one sentence: this list is every metric the company defines. | 78.3% (+3.3 vs off); unanswerable gain did not hold (75% -> 67%); +1.4k tokens/run. | Stopped as pre-registered. |
| **6b. `query_metric` tool (MetricFlow)** | Not started. | `dbt-metricflow` 0.15 installs cleanly with dbt-core 1.11 on Python 3.11 (dry run only). | Not built: the failures are not about metric arithmetic. |

## Findings worth keeping

1. **The measurement was the biggest finding.** At temperature 0 the same prompt is repeatable (3 runs are one sample), but *any* text change is a new draw: renaming one header with no change in content moved the score 18 -> 16, and on the 5b prompt 18 -> 14.
   So single-run differences of 1-4 questions mean nothing; this applies to earlier steps (3d to 4a') too. The same prompt also scored 83.3% and 75.0% at temperature 0.5 on the same day, hours apart.
   What works: compare prompts at `AGENT_TEMPERATURE=0.5` with `RUNS=3`, run at the same time, with the decision rule written before the run (5 points, no loss on the definition questions).
2. **The targeted question was already mostly right.** The plain 4a' prompt passes q06 in about 2 of 3 sampled runs; its earlier single-run failures were mostly an unlucky draw. The relationship ideas aimed at a problem that mostly was not there.
3. **What still fails is behaviour, not missing context:** q19 (invents a cost model for a metric the data cannot hold, 0/3 in every arm), q04 (rounds `numeric_value`), q16/q15 (partial period, relative date), q06 (flips). More generated context did not move these.
4. **Research (web search, 2026-11-05):** SchemaGraphSQL (EACL 2026 findings) uses the foreign-key graph to *select* the few tables a question needs rather than list every path; M-Schema (XiYan-SQL) keeps the schema compact with foreign keys in one place; dbt Labs' 2026 benchmark (a vendor, 11 questions) reports large gains from a semantic layer for the questions it covers. None of this gave a gain on this eval, which has few multi-hop questions and where the metric questions already pass.

## Evidence (all in `eval/results/`, rows in `eval/scoreboard.csv`)

- 5: `step-05-relationship-map_questions_20261105-141003`, baseline the same minute `step-05-baseline-4a-sameday_questions_20261105-140959`.
- 5b and controls: `step-05b-measured-fanout_...144539`, `step-05c-control-A-header_...144720`, `step-05c-5b-with-header-rename_...144851`.
- 5c (sampled, 3 runs): `step-05c-T0.5-baseline-off_...145119`, `step-05c-T0.5-fanout-on_...145119`.
- 6a / 6a': `step-06a-T0.5-metrics-off_...151052`, `step-06a-T0.5-metrics-on_...151052`, `step-06a2-T0.5-metrics-closed_...151404`.

## How to reproduce (on this branch only)

```bash
# the exact 4a' prompt from this code
JOIN_FANOUT=off METRICS=off AGENT_TEMPERATURE=0.5 make eval STEP=<name> RUNS=3
# the metric catalog / the closed catalog
JOIN_FANOUT=off METRICS=on     AGENT_TEMPERATURE=0.5 make eval STEP=<name> RUNS=3
JOIN_FANOUT=off METRICS=closed AGENT_TEMPERATURE=0.5 make eval STEP=<name> RUNS=3
```
The step 5 relationship section is not in the working code any more; it is in commit `9d7151f` (`agent/semantic.py`: `relationships`, `join_paths`, `shared_columns`).

## If someone picks this up

- The one lead: a closed list of company metrics may help the "unanswerable" questions (q18 and q20 in 6a), but it needs more than 3 runs per arm to show, and q19 did not move.
- Only the measurement switches are worth carrying to the agent if wanted: `AGENT_TEMPERATURE` (default 0, no change by default). The context changes (fan-out numbers, metric catalog) should stay off by default: both are on by default on this branch only for the experiments.
- Next targets, as separate steps: q19 (a missing-concept check), q04 (unrounded `numeric_value`), q16 (stop on a partial period).
