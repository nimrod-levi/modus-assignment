# How AI tools were used

Running log. The final write-up for the submission is distilled from this.

## Scaffolding (Claude)

- Generated the initial repo: Makefile, dbt profile for DuckDB, the step 0 agent
  (`agent/`), tests and docs.
- Picked the `jaffle-shop-old` branch because `main` now requires dbt 2.0.
- Profiled the raw CSVs with the DuckDB CLI to find data traps (date range, stores with no
  orders, revenue with vs without tax).

Reviewed by me: _(note what you checked or changed)_

## Not delegated to AI

- The failure taxonomy and the eval questions
- Gold answers (computed by SQL, checked by hand)
- Grading rules

## Where AI got it wrong

_(add moments as they happen: what it produced, how you caught it, what you changed)_
