# How AI tools were used

Running log. The final write-up for the submission is distilled from this.

## Scaffolding (Claude)

- Generated the initial repo: Makefile, dbt profile for DuckDB, the step 0 agent
  (`agent/`), tests and docs.
- Picked the `jaffle-shop-old` branch because `main` now requires dbt 2.0.
- Profiled the raw CSVs with the DuckDB CLI to find data traps (date range, stores with no
  orders, revenue with vs without tax).

- Switched the step 0 agent from the Anthropic API to Gemini (`google-genai`) before any
  score was recorded, so every step uses the same model.

Reviewed by me: _(note what you checked or changed)_

## Not delegated to AI

- The failure taxonomy and the eval questions
- Gold answers (computed by SQL, checked by hand)
- Grading rules

## Where AI got it wrong

- `make profile` crashed with `No module named 'agent'`: the scaffolded script never put the
  repo root on `sys.path`. Caught by running it; fixed in `scripts/profile_data.py`.
- The scaffold's `dbt-core>=1.9,<2` resolved to 1.12, whose install fails on a Python build
  without CA certificates. Pinned to `<1.12`.
- While inspecting a diff, Claude masked only `sk-ant-` keys, so a Gemini key that had been
  added to `.env.example` was printed in the session output. The key was moved to `.env`
  before anything was committed.

_(add moments as they happen: what it produced, how you caught it, what you changed)_
