# Step 1 analysis (tool recovery), run `step-01-tool-recovery_questions_20261103-221238`

Source: `eval/results/step-01-tool-recovery_questions_20261103-221238.json`
Model `openai/gpt-oss-120b` via OpenRouter, provider Cerebras (pinned, no fallbacks), reasoning effort medium, 1 run per question,
prompt sha `73b8c9730f4b`. Per-question table: [`failure_map.csv`](failure_map.csv).

**Score: 13/19 = 68.4%. 0 API errors, 0 rejected tool calls. The run is valid and is on the scoreboard.**

| Outcome | Questions |
|---|---|
| Pass (13) | q01 q02 q03 q05 q06 q07 q08 q09 q10 q11 q12 q13 q14 |
| Wrong: answered when it should decline or ask (5) | q15 q16 q17 q18 q19 |
| Wrong: asked the user instead of `cannot_answer` (1) | q20 |

Per category: metric-definition 100%, units 100%, grain 100%, entity 100%, time 33%, unanswerable 0%.

## 1. What step 1 fixed

Step 0 lost 8 of 20 questions to crashes (a rejected tool call ended the run). Step 1 made `run_sql` the only tool and moved the
final answer to a separate strict `json_schema` request. Result: **no crashes and no rejected calls in 19 questions.**
Every question reached a final answer, so each score now measures the agent's answer, not the plumbing.

Questions that crashed in step 0 and now pass: q08 q10 q11 q12 (all four predicted by the step-0 analysis).

## 2. Two results that are NOT step-1 gains

- **q02 and q06 now pass.** Step 0 failed q02 on join fan-out and q06 crashed on a double count. Step 1 changed the tool contract,
  not the context, so there is no reason the agent should now understand the grain. Most likely run-to-run variance at temperature 0
  with one run per question. Treat them as unstable passes until a second run or the dbt-docs step confirms them.
- **The comparison with step 0 mixes three changes**: the step-1 fix, a provider change (Groq to OpenRouter/Cerebras, step 0 was not
  re-run), and a question set of 19, not 20 (q04 disabled, see STEPS.md). 7/20 to 13/19 is directionally right but not a clean delta.

## 3. What still fails: 6 questions, one root cause

All six are in `time` and `unanswerable`. The agent answers whatever it can compute and never says the data can't support the question.

| Question | What the agent did | Missing |
|---|---|---|
| q15 | Revenue for Aug 2025 ($94,152.63) for "last month" | Data range, and a rule to ask which month |
| q16 | Q3 vs Q2 fall of $66,204, but Q3 has only July and August | Months present per quarter |
| q17 | "Busiest hour is 8 a.m." from midnight-only timestamps | Fact that orders have a date, not a time |
| q18 | Refund rate 0.78% with no refund data | Fact that refunds are not recorded |
| q19 | Net margin 80.37% (revenue minus supplies) | Fact that only supply costs exist |
| q20 | Asked for a target instead of `cannot_answer` | Fact that targets are not recorded, and the difference between missing data and a missing parameter |

None of these is fixable by tool recovery. They need generated context about the data and an explicit "decline when the warehouse
cannot support the question" rule, which is the work of steps 2 and later (dbt docs, profile facts, glossary).

## 4. Cost and speed

- 19,090 tokens per question on average (step 0: 4,070). Most of it is reasoning; q12, q17 and q20 used 11 SQL calls each.
- Median latency about 2 s per question on Cerebras. The same model on Together at default effort took 15 s for q01 (1.4 s on Cerebras).
- The whole eval costs a few cents.

## 5. Provider findings (why Cerebras is pinned)

OpenRouter routes one model slug across about 25 providers, and they differ. On the strict `json_schema` final request:
DeepInfra returned empty content, CoreWeave runaway output, Nebius and Groq-via-OpenRouter empty replies; Together, Parasail,
BaseTen, Crusoe, AkashML and Cerebras returned valid JSON. Together was valid but 10x slower than Cerebras at the same effort.
One-request probes, not a reliability study.
