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

Done: steps 0-5 and holdout 1 (scores in `eval/scoreboard.csv`, one entry per step in STEPS.md, summary table in README.md).
Step 5 (restructured system prompt) is the current agent: 95% on the dev set (3 runs; same-day step-4 baseline 85%),
holdout 1: 8/10 as run, 9/10 after the set-grader eval fix. Agent runs on OpenRouter, `openai/gpt-oss-120b`, provider
pinned to Cerebras (`OPENROUTER_PROVIDER`), reasoning effort medium (`OPENROUTER_REASONING_EFFORT`). Step 0 (7/20) was
measured on Groq and was not re-run on OpenRouter. Evals are deterministic only (no LLM judge).
Not done: glossary retrieval by embeddings (4b), MetricFlow metric tool, holdout at 3 runs, ablation of the step-5 prompt.
`agent/agent.py` holds the current step; earlier steps are git tags. Each fix is its own commit.

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
make eval STEP=step-06-name       # run the eval (needs OPENROUTER_API_KEY)
make ask Q="..."                  # one question, prints SQL steps, saves runs/*.json
make schema                       # the exact system prompt
make db                           # rebuild the warehouse (needs the DuckDB write lock)
```

## Data gotchas

Orders cover 2024-09-01 to 2025-08-31. Only Philadelphia and Brooklyn have orders.
Raw money is in cents, staging and marts in dollars. `order_total` includes tax;
`subtotal` doesn't. Supplies fan out when joined to items.
