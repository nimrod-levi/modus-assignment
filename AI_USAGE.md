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

- q20 "hung" in the 20b eval for 20+ minutes. Claude first suspected a model loop; it was Groq's daily token limit
  (429, 12 min wait) slept through silently by the throttle wrapper. Fixed: the wrapper now fails fast on waits over 120s
  and prints when it waits; the eval now saves results after every question.

- Switched the model client from Groq to OpenRouter (OpenAI SDK, one `make_client()`). Claude planned it, the user decided:
  OpenRouter only, no step-0 re-run, just a note. Claude's first worktree started from an old commit instead of the step-01
  branch and had to be reset; checked before editing.
- First OpenRouter eval attempt ran on gpt-oss-20b (stale `AGENT_MODEL` in `.env`) and failed to produce final JSON. Claude had
  planned the switch without checking that OpenRouter providers differ on strict `json_schema`; a probe across providers found
  it, so the provider is now pinned.

_(add moments as they happen: what it produced, how you caught it, what you changed)_

## Step 2 · optimization
Claude Code diagnosed the token cost from step 1's result file (mean skewed by one 202k-token question), implemented the 5-row cap,
the harness-added truncation assumption, the repeated-SQL reply and the compact schema, and wrote the tests. Note: it first created the
worktree from a stale branch (`baseline-gemini`) and had to reset it onto `main`. The author chose the step number and asked to drop "Done." from the prompt.

## Step 3 · generated structural context
Claude first proposed Cube (`cube_dbt`) after reading its docs. The author asked for another way with auto-generation. Claude then found that the repo
already has `semantic_models`/`metrics` in the dbt YAML, and proposed generating context from the manifest and the warehouse. Claude wrote `agent/semantic.py`
and its tests. Claude's first version missed the inferred joins for `products`, `locations` and `supplies` (their `unique` tests live on the `stg_`
models, not the marts); found by printing the output and reading it, then fixed. A `sed -i` form that fails on macOS silently skipped the
`&&` chain that created the test file; caught because the test run showed failures. Eval for step 3 not yet run.
- Step 3b/3c: Claude's first analysis table of step flips read the wrong results file (`glob` order is not sorted), so several "flips" were
  wrong; found by listing the files by name and recomputing. The first notes layer printed 7 identical "null in 483 rows" lines and
  repeated midnight notes; found by reading the generated prompt and fixed by grouping. The 3c result is a 3-run mean compared with a
  1-run 3b figure, so the effect of the notes alone is not measured.
- Step 3d: Claude wrote the checklist after seeing the failures and said so in STEPS.md. In the wrap-up it compared 3d with 3c per question
  and found the only differences were a grader fix (q08) and an unstable question (q06), so the 75% is not evidence that the checklist helps.

### Step 5 · system prompt rewrite (Claude Code)
Claude researched prompt-writing guidance (Anthropic and OpenAI prompting guides, text-to-SQL practice; mostly secondary summaries found by web search), rewrote `SYSTEM_PROMPT`,
wrote the STEPS entry before the run, ran the baseline and the new eval (3 runs each) and wrote the analysis. What to check: the prompt was written after reading the step-4 failures;
the rewrite is one bundle (no ablation); the verify step it added raised tokens by 35%; q16 regressed.
