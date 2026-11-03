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
Groq (`llama-3.3-70b-versatile`). The eval harness is built (`eval/`, 1 run per question).
Next: run `make eval STEP=step-00-baseline`, record the score in STEPS.md, tag `step-00-baseline`,
then start the fix ladder. Don't change the baseline agent.

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
make eval STEP=step-00-baseline   # run the eval (needs GROQ_API_KEY)
make ask Q="..."                  # one question, prints SQL steps, saves runs/*.json
make schema                       # the exact system prompt
make db                           # rebuild the warehouse (needs the DuckDB write lock)
```

## Data gotchas

Orders cover 2024-09-01 to 2025-08-31. Only Philadelphia and Brooklyn have orders.
Raw money is in cents, staging and marts in dollars. `order_total` includes tax;
`subtotal` doesn't. Supplies fan out when joined to items.
