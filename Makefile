PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: web glossary-check checks setup check-python venv db test profile schema ask eval eval-holdout eval-tables eval-test clean

## setup: create the venv, install deps and build the warehouse (run once)
setup: venv db

check-python:
	@$(PYTHON) -c 'import sys; v = sys.version_info[:2]; ok = (3, 10) <= v <= (3, 13); print(f"Python {v[0]}.{v[1]}" + ("" if ok else " is not supported by dbt here: use 3.10-3.13, e.g. make setup PYTHON=python3.12")); sys.exit(0 if ok else 1)'

venv: check-python
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r requirements.txt

## db: rebuild data/jaffle.duckdb from the dbt project
db:
	PATH="$(abspath $(BIN)):$$PATH" bash scripts/build_db.sh

## test: SQL guard, read-only checks and the agent loop (no API key needed)
test:
	$(BIN)/python -m pytest -q

## profile: row counts, date range, revenue both ways
profile:
	$(BIN)/python scripts/profile_data.py

## checks: run the edge-case checklist on every table and print the generated context
checks:
	$(BIN)/python -m agent.edge_cases

## glossary-check: validate glossary/glossary.yaml against the warehouse and print what the agent receives
glossary-check:
	$(BIN)/python -m agent.glossary

## schema: print the baseline system prompt
schema:
	$(BIN)/python -m agent --schema

## ask: make ask Q="What was our revenue last month?"
ask:
	$(BIN)/python -m agent --trace "$(Q)"

## eval: make eval STEP=step-00-baseline [ONLY=q01,q02] [RUNS=1]  (needs OPENROUTER_API_KEY)
eval:
	@test -n "$(STEP)" || { echo "usage: make eval STEP=step-00-baseline [ONLY=q01,q02]"; exit 1; }
	$(BIN)/python -m eval.run_eval --step "$(STEP)" $(if $(ONLY),--only $(ONLY)) $(if $(RUNS),--runs $(RUNS))

## eval-holdout: run eval/holdout.yaml (once, at the end of a step) [ONLY=h01,h02] [RUNS=1]
eval-holdout:
	@test -n "$(STEP)" || { echo "usage: make eval-holdout STEP=holdout-02 [ONLY=h01,h02] [RUNS=1]"; exit 1; }
	$(BIN)/python -m eval.run_eval --step "$(STEP)" --file eval/holdout.yaml $(if $(ONLY),--only $(ONLY)) $(if $(RUNS),--runs $(RUNS))

## eval-tables: run eval/tables.yaml (list and table answers) [ONLY=t01,t02] [RUNS=1]
eval-tables:
	@test -n "$(STEP)" || { echo "usage: make eval-tables STEP=step-06-name [ONLY=t01,t02] [RUNS=1]"; exit 1; }
	$(BIN)/python -m eval.run_eval --step "$(STEP)" --file eval/tables.yaml $(if $(ONLY),--only $(ONLY)) $(if $(RUNS),--runs $(RUNS))

## eval-test: grader and runner tests (no API key)
eval-test:
	$(BIN)/python -m pytest -q tests/test_eval_grade.py

## web: one-page UI to ask a question and see the SQL steps (http://127.0.0.1:8000)
web:
	$(BIN)/python -m agent.web

clean:
	rm -rf $(VENV) data/jaffle.duckdb data/jaffle.duckdb.wal dbt/target dbt/dbt_packages dbt/logs
