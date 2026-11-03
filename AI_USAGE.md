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

- Claude analysed the step-00 run (`eval/analysis/`) and spotted that 8 of 20 results were API crashes, not agent
  mistakes. The author decided to record the 35% as-is, flagged, and to keep evals deterministic for now.

- Step 1: Claude first read the Groq `tool_use_failed` errors as "the model calls a tool that does not exist" and planned
  retries plus clearer wording. The author questioned it; the raw `failed_generation` showed `json` / `commentary` are
  gpt-oss output-format names, not tools, and some "calls" were plain prose. Claude's own added "JSON object" wording in the
  prompt was probably part of the trigger (10 rejections remained). Fix: `run_sql` is the only tool and the final answer is a
  separate strict `json_schema` request. Checked only with unit tests and 2 single-question smoke runs on gpt-oss-20b
  (q10, q07: 0 rejections); the real check is the eval on the 120b.
- Claude ran several experiments through `| tail`, so output was invisible, and misread Groq's daily-token-limit
  429 wait (silently slept by the throttle wrapper) as a hang. Found by calling the API directly.

_(add moments as they happen: what it produced, how you caught it, what you changed)_
