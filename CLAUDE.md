# CLAUDE.md

Instructions for Claude Code working in this repo. Read README.md for setup and layout.

## What this project is

A take-home for Modus (they sell a "Context Warehouse": it mines how a business works
from dbt, code, docs and queries, and gives each AI agent only the relevant context).
The task: build a data agent over the jaffle-shop DuckDB warehouse, write a ~20-question
eval, then improve the agent step by step and show the score after every step. Part 2 is a
customer scenario: the agent gave the customer's CFO a wrong revenue number.

The story the repo must tell: **same database, same model; better context and tools →
higher score**, with every step measured and reproducible.

## Current step

Step 0 (baseline) is done: `agent/agent.py` with schema names + `run_sql` + `submit_answer`, on
Groq (`openai/gpt-oss-120b`); since the provider switch (below) the agent runs on OpenRouter, same model. The eval harness is built (`eval/`, 1 run per question).
Baseline recorded: 7/20 = 35%, with 8 Groq tool-call crashes (flagged in `eval/scoreboard.csv` and STEPS.md).
Evals are deterministic only for now (author's decision; a judge may come later).
Step 1 (tool recovery) is scored: 13/19 = 68.4%, 0 errors, 0 rejections (`eval/scoreboard.csv`, analysis in
`eval/analysis/step-01-tool-recovery_20261103-221238/`). `run_sql` is the only tool, the final answer is a separate strict
`json_schema` request, rejected replies are retried (cap 3, -10% credit each). q04 is disabled (19 questions; see STEPS.md).
Remaining failures q15-q20 need context.
Step 2 (optimization) and step 3 (generated context from manifest + warehouse; 3b refusal sentence, 3c notes, 3d fixed edge-case checklist in
`agent/edge_cases.py`) are scored: 3d = 15/20 = 75% at 1 run (not optimal; see STEPS.md). q04 is back on (20 questions). Remaining failures q03 q04 q15 q16 q19
are definitions and missing concepts. Step 4 (customer glossary, `glossary/glossary.yaml`: concepts only, all assumed) 4a' = 18/20 = 90% at 1 run (q04 wording eval fix in between). Open: q16 and q19. Next: embedding retrieval of glossary entries (4b), holdout runs, then the MetricFlow metric tool.
Provider switch: Groq -> OpenRouter (same model slug, bigger usage plan, OpenAI SDK; the Groq SDK is gone). Step 0 was NOT re-run;
its 7/20 was measured on Groq and is not strictly comparable (see STEPS.md note). Step 1 is the first score on OpenRouter.
Agent runs on OpenRouter, provider pinned to Cerebras (`OPENROUTER_PROVIDER`), reasoning effort medium (`OPENROUTER_REASONING_EFFORT`).
Don't change the step-00 agent in place; each fix is its own commit and tag.

## Rules

- **Keep step 0 thin.** It's the control group. Improvements go in later steps, one root
  cause per step, each its own commit and tag (`step-01-dbt-docs`, ...).
- **Never edit an eval question or gold answer to make the agent pass.** If a question is
  wrong, fix it as its own "eval fix" commit and log the reason in STEPS.md.
- **Gold answers are computed by `gold_sql`, never typed by hand.** Each one is hand-checked once.
- **Grade deterministically first** (numbers with tolerance and unit, sets, `status`). Use an
  LLM judge only for free text, with a rubric.
- **Context must be generated, not hand-written into prompts.** Later steps mine
  `dbt/target/manifest.json` and the model YAML. Customer answers (revenue definition,
  fiscal calendar) go in a separate, clearly labelled glossary file.
- **No few-shot examples taken from the eval set** and no question-specific rules in prompts.
- **Write the STEPS.md entry (hypothesis, expected fixes) before running the eval.**
- **Plain Python, no agent frameworks.** Every line must be explainable in a 25-minute review.
- Log notable AI-assisted work, and anything AI got wrong, in AI_USAGE.md.

## Commands

```bash
make test                         # no API key needed
make eval STEP=step-00-baseline   # run the eval (needs OPENROUTER_API_KEY)
make ask Q="..."                  # one question, prints SQL steps, saves runs/*.json
make schema                       # the exact system prompt
make db                           # rebuild the warehouse (needs the DuckDB write lock)
```

## Data gotchas

Orders cover 2024-09-01 to 2025-08-31. Only Philadelphia and Brooklyn have orders.
Raw money is in cents, staging and marts in dollars. `order_total` includes tax;
`subtotal` doesn't. Supplies fan out when joined to items.
