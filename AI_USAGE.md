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
- Switched the step 0 agent from Gemini to Groq (`groq` SDK, `llama-3.3-70b-versatile`) for higher
  rate limits. Same tools and loop; only the client layer changed. No score had been recorded yet.
- Ported the eval runner's rate-limit wrapper to Groq and made it run 1 run per question.

- Built the eval harness (`eval/grade.py`, `eval/run_eval.py`, tests, Makefile targets).
- Drafted the 20 eval questions in `eval/questions.yaml` after probing the warehouse (Brooklyn's
  `opened_date` vs first order, 483 empty $0 orders, duplicate customer names, midnight-only
  timestamps, partial Q3, `customer_type` meaning). I asked for this, so the question wording and
  failure categories started as AI output.

## Not delegated to AI

- Hand-checking each gold result once, and deciding which questions stay (TODO: do this before the baseline run)
- Deciding that "revenue" means pre-tax (q01 gold): an assumption to confirm with the customer
- Gold answers are computed by SQL, never typed

## Where AI got it wrong

- Claude's `pip download groq` dropped 20 `.whl` files into the repo root, and the first Groq
  commit left `pyyaml` out of `requirements.txt`. Both were found while cleaning up and fixed.

- `make profile` crashed with `No module named 'agent'`: the scaffolded script never put the
  repo root on `sys.path`. Caught by running it; fixed in `scripts/profile_data.py`.
- The scaffold's `dbt-core>=1.9,<2` resolved to 1.12, whose install fails on a Python build
  without CA certificates. Pinned to `<1.12`.
- While inspecting a diff, Claude masked only `sk-ant-` keys, so a Gemini key that had been
  added to `.env.example` was printed in the session output. The key was moved to `.env`
  before anything was committed.

_(add moments as they happen: what it produced, how you caught it, what you changed)_
