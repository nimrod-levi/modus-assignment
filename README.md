# Modus home assignment: a data agent over jaffle-shop

An AI agent that answers business questions over a DuckDB warehouse, the eval that measures it, and a step-by-step log of
improving it. The warehouse is dbt Labs' jaffle-shop sample, built locally with dbt. The model stays the same throughout
(`openai/gpt-oss-120b`); what changes is the context and the tools the agent gets, and every step is scored.

- **Result:** 35% at step 0 → **95%** on the 20-question dev set at step 5 (3 runs), and **9/10 on 10 held-out questions**
  written after the step-5 agent was built (8/10 as run, 9/10 after a grader fix; see [Limitations](#limitations)).
- **Step 6 (list and table answers):** the agent can fetch up to 200 rows and return a `table`; a new 4-question tables suite
  goes from 0% to 75-83%. It costs about 8 points on the dev set against a same-day step-5 run (see STEPS.md).
- **[STEPS.md](STEPS.md):** one entry per step: hypothesis (written before the run), change, result, what it does and does not show.
- **[eval/scoreboard.csv](eval/scoreboard.csv):** one row per scored run. Per-question analyses are in [`eval/analysis/`](eval/analysis/).
- **[AI_USAGE.md](AI_USAGE.md):** how AI tools were used, and where they got it wrong.
- Part 2 of the assignment (the customer scenario) is answered separately.

## Results

| Step | What changed | Score | Runs | Tokens/run |
| --- | --- | --- | --- | --- |
| 0 baseline | table and column names, `run_sql` + `submit_answer` tools (on Groq) | 7/20 = 35% (8 API crashes) | 1 | 4,070 |
| 1 tool recovery | `run_sql` is the only tool; final answer is a separate strict-JSON request; provider moved to OpenRouter | 13/19 = 68.4% | 1 | 19,090 |
| 2 optimization | 5-row result cap, compact schema, no repeated queries | 13/19 = 68.4% | 1 | 7,043 |
| 3 generated structure | grain, keys, joins and data facts generated from the dbt manifest and the warehouse | 10/20 = 50% | 1 | 10,191 |
| 3b refusal sentence | one generic rule: no data for the concept → `cannot_answer`; ambiguous → ask | 14/20 = 70% | 1 | 7,478 |
| 3c table notes | generated per-table warnings (midnight timestamps, partial quarters, ...) | 66.7% | 3 | 8,670 |
| 3d edge-case checklist | a fixed 11-check data-quality checklist replaces the hand-picked notes | 15/20 = 75% | 1 | 11,506 |
| 4a glossary | customer definitions file (all assumed), sent with the question | 16/20 = 80% | 1 | 10,191 |
| 4a' glossary, concepts only | dates and names removed from the glossary | 18/20 = 90% | 1 | 10,822 |
| 4a3 (eval fix) | q04 graded with zero tolerance | 17/20 = 85% | 1 | 10,822 |
| 4 final | same agent as 4a', re-run a day later | 18/20 = 90% | 3 | 10,959 |
| 5 baseline re-run | same agent again, same day as step 5 | 85% | 3 | 10,663 |
| **5 system prompt** | restructured prompt: role, workflow, grounding and precision rules | **95%** | 3 | 14,430 |
| **holdout 1** | 10 new questions, step-5 agent | **8/10 as run, 9/10 re-graded** | 1 | 14,245 |
| 5 re-run (day of step 6) | step-5 agent, dev set, two runs | 91.7%, 88.3% | 3 | 13,641–13,933 |
| 5 on tables suite | step-5 agent, 4 list questions (`eval/tables.yaml`) | 0% (no `table` field; invents rows past the 5-row cap) | 3 | 26,190 |
| 6 table answers | `run_sql` `max_rows` up to 200; `table` {columns, rows} in the final answer | tables 83.3% · dev 80.0%, 83.3% | 3 | 18,226 · ~14,300 |
| **6b side effects** | final request back to the step-5 text; `max_rows` can only raise the cap | **tables 75% · dev 81.7%** | 3 | 20,560 · 14,791 |

Read the deltas with the caveats in [Limitations](#limitations): the same agent scores 85–90% on different days, so a step
is only compared with a baseline run on the same day.

Git tags mark the scored states: `step-00-baseline`, `step-01-tool-recovery-scored`, `step-02-optimization`,
`step-03d-edge-case-checklist`, `step-04-final`, `step-05-system-prompt`, `step-06-table-answers`, `step-06b-side-effects`.
The `step-06-table-answers` branch holds step 6b; `main` holds step 5.

## Setup (once)

You need Python 3.10–3.13, internet access (pip and dbt Hub) and an [OpenRouter](https://openrouter.ai) API key.

```bash
make setup                      # venv + deps + builds data/jaffle.duckdb (~1-2 min)
cp .env.example .env            # then paste your OPENROUTER_API_KEY
make test                       # should be all green; no API key needed
```

If `python3 --version` says 3.14 or newer, dbt may not install. Run `make setup PYTHON=python3.12` instead.

## Commands

| Command | What it does |
| --- | --- |
| `make ask Q="What was our revenue in July 2025?"` | Ask the agent; prints each SQL step and the answer, saves a trace to `runs/` |
| `make web` | One-page UI at http://127.0.0.1:8000: answer, assumptions and every SQL step |
| `make eval STEP=my-run [RUNS=3] [ONLY=q01,q02]` | Run the 20-question eval; writes `eval/results/*.json` and (for a full run) a scoreboard row |
| `make eval-holdout STEP=my-run [RUNS=3]` | Run the 10 held-out questions |
| `make eval-tables STEP=my-run [RUNS=3]` | Run the 4 list/table questions (`eval/tables.yaml`) |
| `python -m eval.regrade eval/results/<file>.json` | Re-grade a stored run with the current grader (no model calls) |
| `make schema` | Print the exact system prompt the agent sees |
| `make checks` | Run the edge-case checklist on every table and print the generated context |
| `make glossary-check` | Validate `glossary/glossary.yaml` against the warehouse and print the block the agent receives |
| `make profile` | Row counts, date range, revenue both ways, orders by store |
| `make test` | Unit tests: SQL guard, read-only access, agent loop with a fake LLM, grader, checklist, glossary |
| `make db` | Rebuild the warehouse from `dbt/` (close any running agent first: dbt needs the write lock) |

Configuration lives in `.env` (see `.env.example`): `AGENT_MODEL`, `OPENROUTER_PROVIDER` (pinned to Cerebras, no
fallbacks), `OPENROUTER_REASONING_EFFORT` (medium), and `GLOSSARY=off|all`.

## How the agent works

Plain Python and the OpenAI SDK pointed at OpenRouter; no agent framework.

- **System prompt** (`agent/agent.py`): role, a five-step workflow (understand, check feasibility, query, verify, answer) and
  rules (every figure comes from a query; use a column only for what its description says; ask when a missing detail changes
  the answer; keep full precision). Around it sits the generated warehouse context.
- **Generated context** (`agent/semantic.py`, `agent/edge_cases.py`): nothing hand-written. From `dbt/target/manifest.json`
  it takes model and column descriptions, grain (from `unique` tests and primary keys) and join paths (from `relationships`
  tests, plus inferred ones, labelled). From the warehouse it computes row counts, low-cardinality values and the results
  of a fixed 11-check edge-case checklist run on every table (date coverage and partial periods, date-only timestamps, nulls,
  zeros, negatives, duplicate keys, orphans, constants, placeholders, cents vs dollars), plus fan-out and many-to-many join risks.
- **Customer glossary** (`glossary/glossary.yaml`, `agent/glossary.py`): the only hand-written context, kept in its own
  labelled file: what "revenue", "new customer" and "gross profit" mean, which orders count, how to treat relative dates.
  Each entry has an owner, a date and a status; **all ten are the author's assumptions**, shown to the agent as `(assumed)`.
  It is validated against the warehouse (tables, columns, SQL snippets) and sent with the question, not in the system prompt.
- **Loop:** `run_sql` is the only tool (up to 12 turns, temperature 0). A reply without a tool call ends exploration; the final
  answer is then a separate request with no tools and a strict JSON schema: `answer`, `numeric_value`, `table` (columns and rows
  for a list answer, copied by the model from a query result; null otherwise), `unit`, `sql`,
  `definition_used`, `assumptions`, `status` (`answered` | `needs_clarification` | `cannot_answer`). A rejected reply is
  retried with feedback (at most 3 per question; each costs 10% of that question's credit). A repeated query is not re-run.
- **Safety** (`agent/db.py`): the DuckDB file is opened read-only; external file and URL access is off and locked (so
  `read_csv('/etc/passwd')` fails); one SELECT/WITH statement per call; 5 rows shown to the model per query by default, up to 200 when it passes `max_rows`
  (cells cut at 60 characters); 20 s timeout.
- **Trace** (`runs/*.json`, `eval/results/*.json`): model, provider, prompt hash, glossary hash, every SQL call with row count,
  error and timing, tokens, latency and the final answer.

## The eval

- `eval/questions.yaml`: 20 questions in six categories (metric definition, units, grain, entity, time, unanswerable), each
  aimed at a named trap (tax-inclusive vs pre-tax revenue, supplies fan-out, stores with no orders, the data ending in August
  2025, concepts the warehouse does not hold).
- `eval/holdout.yaml`: 10 further questions written after the step-5 agent was built and run once; not used for tuning.
- `eval/tables.yaml`: 4 questions whose answer is a list (10-69 rows), added at step 6 and kept apart from the dev set.
- **Gold answers come from `gold_sql`**, run against the warehouse at eval time, never typed by hand.
- **Grading is deterministic** (`eval/grade.py`): a number within tolerance and with an accepted unit, a set of names that must
  appear in the answer, a `table` that must hold exactly the gold rows (columns matched by value, numbers rounded to 2 decimals),
  or the submitted `status` only (for questions where the right move is to ask or refuse). No LLM judge.
- **Score** = mean credit per question; `pass_all` (pass^k) = share of questions that passed every run.
- Questions, gold SQL and graders are changed only in their own "eval fix" commit, with the reason logged in STEPS.md.

## Repo layout

```
agent/
  agent.py       system prompt, run_sql tool, the loop, the final-answer request, the trace
  semantic.py    generated warehouse context from the dbt manifest and the data
  edge_cases.py  the fixed edge-case checklist, run on every table
  glossary.py    loads, validates and renders the customer glossary
  db.py          read-only DuckDB access: connect, SQL guard, run_sql, describe_schema
  web.py         one-page web UI (stdlib http.server)
  __main__.py    CLI: python -m agent "question" [--trace] [--schema] [--model ...]
eval/
  questions.yaml, holdout.yaml, tables.yaml   the questions with gold_sql and graders
  run_eval.py, grade.py          runner and deterministic grader
  regrade.py                     re-grade a stored run after an eval fix
  results/       one JSON per run (every answer, step and verdict)
  analysis/      per-step analysis: failure map and write-up
  scoreboard.csv one row per scored run
glossary/        glossary.yaml: customer definitions (all assumed)
dbt/             jaffle-shop dbt project (the customer's "business context"; not modified)
data/            jaffle.duckdb lands here (git-ignored, rebuild with make db)
scripts/         build_db.sh, profile_data.py
tests/           pytest, no API key needed
STEPS.md         one entry per step: hypothesis, change, result
AI_USAGE.md      how AI tools were used, and what they got wrong
CLAUDE.md        instructions for Claude Code sessions in this repo
```

## The warehouse

`make db` runs dbt (`seed`, `build`, `docs generate`) into one DuckDB file with three layers. The agent sees all three, as it
would in a real warehouse.

| Layer | Schema | Built as | Examples |
| --- | --- | --- | --- |
| Raw seeds | `raw` | tables | `raw.raw_orders`, `raw.raw_items`, `raw.raw_stores` (money in **cents**) |
| Staging | `main` | views | `main.stg_orders`, `main.stg_order_items` (money in dollars) |
| Marts | `main` | tables | `main.orders`, `main.order_items`, `main.customers`, `main.locations` |

Data facts the eval relies on (recompute with `make profile`):

- Orders run from **2024-09-01 to 2025-08-31**: 61,948 orders from 935 customers. Timestamps are all midnight.
- **Six stores exist, but only Philadelphia (39,931 orders) and Brooklyn (22,017) have orders.** Brooklyn's first order is
  2025-03-12, although `locations.opened_date` says 2017-03-12.
- **Revenue two ways:** pre-tax subtotal **$637,444.00** vs total including tax **$671,425.37** (+5.3%).
- 483 orders have no items and a $0 total. 935 customer ids share 930 names.
- `raw_supplies` has 65 rows for 29 supply ids across 10 SKUs, so joining supplies to items multiplies rows.
- There are no refunds, targets, labour or rent costs, suppliers or hours of the day.

## Limitations

What a reviewer should know before trusting the numbers:

1. **Step 0 → 1 mixes two changes.** Step 0 ran on Groq and 8 of its 20 answers were API crashes. Step 1 fixed the tool contract
   *and* moved to OpenRouter/Cerebras; step 0 was not re-run there. Steps 1–2 also used 19 questions (q04 was disabled).
2. **The dev set was used for tuning.** The refusal sentence, table notes, checklist, glossary entries and step-5 prompt were
   written after reading the dev-set failures (generic rules, no question-specific ones, but chosen by those failures). The
   95% overstates performance on new questions; the holdout (9/10, one run) is the fairer figure, and 10 questions is small.
3. **Provider drift.** With no change on our side, the same agent scored 85% and 90% on different days and every answer text
   changed. Within one session repeated runs are identical, so "3 runs" there carry the confidence of one. Scores are
   compared only with a same-day baseline.
4. **The eval changed during the project**, each change in its own commit and logged in STEPS.md: q01 now asks for revenue
   including tax; q04 was disabled, re-enabled, reworded ("exactly") and graded at zero tolerance; q08 accepts the unit
   "drink items"; the set grader ignores Unicode spaces (holdout h06 went from fail to pass on re-grade).
5. **The glossary is assumed, not confirmed.** No customer has signed off any entry ("Maya" is a placeholder owner). The agent
   is told the entries are customer definitions, each marked `(assumed)`. Different customer answers would change the correct
   answers to several questions. The whole file is sent with every question; at scale it needs retrieval.
6. **Deterministic grading only.** Free-text reasoning and the stated assumptions are not graded; the set grader cannot catch
   extra, wrong items; status questions accept either asking or declining.
7. **Reproducibility.** Runs were made on an uncommitted working tree, so a scoreboard `git_sha` is the commit *before* the
   change; the prompt hash identifies the prompt. Until the final review the `dirty` flag was always true (bug) and the glossary
   text had no hash. STEPS entries and their results were often committed together, so "hypothesis before the run" cannot be
   shown from git history alone.
8. **Cost and staleness.** Step 5 costs 35% more tokens than step 4 (its verify step re-queries), and its parts were not
   tested separately. The generated context is computed when the prompt is built, with no refresh or freshness check for a
   warehouse that changes.
9. **Step 6 trades dev-set accuracy for list answers.** About 8 points against a same-day step-5 run, spread over several questions,
   cause not isolated. Its largest failure mode, a placeholder figure with no query behind it, exists at step 5 too and needs a
   harness guard. The tables suite has 4 questions; a table cell longer than 60 characters arrives cut and is copied with "...".
10. **Not done:** glossary retrieval by embeddings, a metric tool over the dbt semantic layer (MetricFlow), holdout at 3 runs,
   new holdout questions after holdout 1's failures became known.
