.PHONY: setup check build docs clean

setup:  ## Install the Python env, dbt packages and the git pre-push hook
	uv sync
	uv run dbt deps
	uv run pre-commit install

check:  ## Run every repo check, including dbt build (the pre-push hook; CI skips dbt build)
	uv run pre-commit run --all-files --hook-stage pre-push

build:  ## Build models, seeds and tests in BigQuery
	uv run dbt build

docs:  ## Generate and serve dbt docs
	uv run dbt docs generate
	uv run dbt docs serve

clean:
	uv run dbt clean
