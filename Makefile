PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: setup check-python venv db test profile schema ask clean

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

## schema: print the baseline system prompt
schema:
	$(BIN)/python -m agent --schema

## ask: make ask Q="What was our revenue last month?"
ask:
	$(BIN)/python -m agent --trace "$(Q)"

clean:
	rm -rf $(VENV) data/jaffle.duckdb data/jaffle.duckdb.wal dbt/target dbt/dbt_packages dbt/logs
