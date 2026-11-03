# Modus home assignment: a data agent over jaffle-shop

An AI agent that answers business questions over a DuckDB warehouse, plus the eval
that measures it. The warehouse is dbt Labs' jaffle-shop sample, built locally with dbt.

**Status:** Step 0, the baseline agent, is built. The eval and the fixes come next (see
[Next steps](#next-steps)).

## Setup (once)

You need Python 3.10–3.13, internet access (pip and dbt Hub) and a Groq API key.

```bash
cd ~/code/modus-assignment
make setup                      # venv + deps + builds data/jaffle.duckdb (~1-2 min)
cp .env.example .env            # then paste your GROQ_API_KEY
make test                       # should be all green; no API key needed
```

If `python3 --version` says 3.14 or newer, dbt may not install. Run
`make setup PYTHON=python3.12` instead (or `uv python install 3.12` first).

## Daily commands

| Command | What it does |
| --- | --- |
| `make ask Q="What was our revenue last month?"` | Ask the agent; prints each SQL step and the answer, saves a trace to `runs/` |
| `make schema` | Print the exact system prompt the agent sees |
| `make profile` | Row counts, date range, revenue both ways, orders by store |
| `make test` | SQL guard, read-only checks, agent loop with a fake LLM |
| `make db` | Rebuild the warehouse from `dbt/` (close any running agent first: dbt needs the write lock) |

## Repo layout

```
agent/
  db.py          read-only DuckDB access: connect, SQL guard, run_sql, describe_schema
  agent.py       the step 0 agent: system prompt, tools, the tool-use loop, the trace
  __main__.py    CLI: python -m agent "question" [--trace] [--schema] [--model ...]
dbt/             jaffle-shop dbt project (the customer's "business context")
data/            jaffle.duckdb lands here (git-ignored, rebuild with make db)
scripts/         build_db.sh, profile_data.py
tests/           pytest
runs/            ad-hoc traces from make ask (git-ignored)
STEPS.md         one entry per improvement step: hypothesis, change, result
AI_USAGE.md      running log of how AI tools were used (part of the deliverable)
CLAUDE.md        instructions for Claude Code sessions in this repo
```

## The warehouse

`make db` runs dbt (`seed`, `build`, `docs generate`) into one DuckDB file with three layers.
The agent sees all three, the way it would in a real warehouse.

| Layer | Schema | Built as | Examples |
| --- | --- | --- | --- |
| Raw seeds | `raw` | tables | `raw.raw_orders`, `raw.raw_items`, `raw.raw_stores` (money in **cents**) |
| Staging | `main` | views | `main.stg_orders`, `main.stg_order_items` (money in dollars) |
| Marts | `main` | tables | `main.orders`, `main.order_items`, `main.customers`, `main.locations` |

dbt also writes `dbt/target/manifest.json` and `catalog.json`. Those hold the model docs,
column descriptions, semantic models and metrics. The baseline ignores them on purpose.

### Data facts worth knowing (profiled from the raw CSVs)

- Orders run from **2024-09-01 to 2025-08-31**: 61,948 orders from 935 customers.
  Write time-based questions for 2024–2025, and decide what "last month" means when the data ends in August 2025.
- **Six stores exist, but only Philadelphia (39,931 orders) and Brooklyn (22,017) have
  orders.** Chicago, San Francisco, New Orleans and Los Angeles have none. That makes
  them good entity and false-premise questions.
- **Revenue two ways:** pre-tax subtotal **$637,444.00** vs total including tax
  **$671,425.37** (+5.3%). That's the CFO trap.
- Raw money columns are cents (BIGINT); staging and marts are dollars.
- 483 orders have no items (61,948 orders, 61,465 with items).
- `raw_supplies` has 65 rows for 29 supply ids across 10 SKUs, so joining supplies to
  items multiplies rows. That's a good grain / fan-out question.

Recompute these with `make profile` after your first build and treat that output as the source of truth.

## How the baseline agent works

- **Prompt:** one paragraph plus every table and view with its columns, from
  `information_schema`. No docs, no metric definitions, no business rules.
- **Tools:** `run_sql(sql)` and `submit_answer(answer, numeric_value, unit, sql,
  definition_used, assumptions, status)`. `status` is `answered`, `needs_clarification`
  or `cannot_answer`. The structured answer is what the eval will grade.
- **Loop:** up to 12 model turns at temperature 0. If the model stops without
  submitting, it gets one nudge. On the last turn it is forced to call `submit_answer`.
- **Safety (`agent/db.py`):** the file opens read-only; external file and URL access is
  off and locked (so `read_csv('/etc/passwd')` fails); only one SELECT/WITH per call;
  200-row cap; 20 s timeout.
- **Trace (`runs/*.json`):** model, temperature, system-prompt hash, every SQL call with
  row count, error and timing, total tokens, latency and the submitted answer.

## Next steps

- [ ] `make setup`, `make test`, `make profile`; fix anything that breaks
- [ ] Ask 5–10 questions by hand (`make ask`); read the traces; note where it fails
- [ ] Commit, then `git tag step-00-baseline`
- [ ] Email Modus the customer questions (revenue definition, fiscal calendar, "new customer", access rules)
- [ ] Build the eval: `eval/questions.yaml` (20 questions + `gold_sql`), `eval/run_eval.py`
      (1 run per question by default, deterministic grading, `scoreboard.csv`), `eval/holdout.yaml`
- [ ] Record the step 0 score in `STEPS.md`, then start the fix ladder

## Push to GitHub

```bash
gh repo create modus-assignment --private --source . --push
```
