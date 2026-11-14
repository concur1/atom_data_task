# Agent instructions

## Tooling

- Use `uv` for everything Python: dependencies, virtualenvs, and running tools. Never call bare `python`/`pip`.
- dbt Core on BigQuery (`dbt-bigquery`), run via `uv run dbt ...`.
- Python (marimo notebooks): lint/format with `ruff`, type-check with `ty`.
- SQL: lint/fix with `sqruff` (BigQuery dialect, jinja templater; config in `.sqruff`).
- Checks are defined once in `.pre-commit-config.yaml` (pre-push stage). They also run in GitHub Actions (without `dbt-build`, which needs BigQuery) and from the Claude Code pre-push hook in `.claude/`.

## Commands

- Setup: `make setup`
- Build models, seeds and tests: `make build`
- All checks: `make check`
- Add a dependency: `uv add <pkg>` / `uv add --dev <pkg>`

## Working rules

### General
- At the end of **every** task, run `make check` (includes `dbt build`) and make it pass.
- Work in thin stacked PRs: one branch per task, each branched off the previous task's branch (`01-...`, `02-...`).

### dbt / BigQuery
- Medallion layers: `models/bronze/` (sources on `de_raw` plus their tests), `models/silver/` (cleaned, conformed), `models/gold/` (outputs).
- All models build into one dataset (`owen_cain` by default), so prefix model names with their layer: `<layer>__<entity>`, e.g. `silver__responses`.
- Ask the user before adding a new table/model and deciding which layer it lives in.
- Write down every interpretation of ambiguous data (in the README's assumptions section).

### Testing
- Test behaviour, not implementation.
- Before creating tests, confirm with the user what behaviour we should enforce.

### Reconciliation

Verify that a pipeline is working as expected by creating a reconciliation notebook in the `notebooks/` folder.
Reconciliation notebooks should:
- Run the pipeline
- Run checks such as:
    - A before/after comparison
    - Check for duplicates
    - Check for nulls
    - Count the rows
    - Check for gaps in the input data
