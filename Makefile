.PHONY: all generate ingest seed build test export lint clean

DBT = cd dbt && dbt

all: generate ingest seed build export  ## full pipeline from scratch

generate:  ## create synthetic vendor files in data/raw
	python3 src/generate_data.py --out data/raw

ingest:  ## load vendor files into DuckDB (idempotent upsert + quarantine)
	python3 src/ingest.py --raw-dir data/raw --db data/warehouse.duckdb

seed:  ## stage the property reference file as a dbt seed
	mkdir -p dbt/seeds
	cp data/raw/properties.csv dbt/seeds/properties.csv
	$(DBT) seed --profiles-dir .

build:  ## dbt build = run models + all tests
	$(DBT) build --profiles-dir . --exclude properties

export:  ## write marts to parquet for downstream consumers (P2/P3)
	python3 src/export_marts.py --db data/warehouse.duckdb --out exports

test:  ## python unit tests
	python3 -m pytest tests/ -q

lint:
	ruff check src/ tests/

docs:  ## generate dbt docs site into dbt/target
	$(DBT) docs generate --profiles-dir .

clean:
	rm -rf data/warehouse.duckdb dbt/target exports