#!/usr/bin/env bash
# Build data/jaffle.duckdb from the dbt project: seeds -> staging views -> marts,
# run dbt's tests, and generate docs (target/manifest.json + catalog.json are the
# raw material for later context-mining steps).
set -euo pipefail

cd "$(dirname "$0")/../dbt"
export DBT_PROFILES_DIR="$PWD"
mkdir -p ../data
rm -f ../data/jaffle.duckdb ../data/jaffle.duckdb.wal

dbt deps
dbt seed --full-refresh --vars '{"load_source_data": true}'
dbt build
dbt docs generate

echo
echo "Built $(cd ../data && pwd)/jaffle.duckdb"
