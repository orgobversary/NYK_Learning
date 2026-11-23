# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11+ ETL learning project using a `src/` layout. Core ingestion, validation, and release-building logic lives in `src/knicks_history/pipeline.py`; `cli.py` exposes the `knicks` command. Keep offline tests in `tests/`, synthetic inputs in `fixtures/`, coverage expectations in `config/`, consumer queries in `sql/`, operational helpers in `scripts/`, and setup or dataset documentation in `docs/`. Generated snapshots and staged releases belong under ignored `data/` and `build/` directories, never in source control.

## Build, Test, and Development Commands

Create an isolated environment and install the editable package:

```bash
python3 -m venv .venv-knicks
source .venv-knicks/bin/activate
python -m pip install -e '.[columnar]'
```

Run `python -m unittest discover -s tests -v` for the full suite. Exercise the offline workflow with:

```bash
knicks ingest --input fixtures/league-demo.json --synthetic --season 2024-25 --root data/demo
knicks build --root data/demo --expected config/expected-demo.csv --parquet
```

Use `python scripts/stage_release.py data/demo build/preview-demo` to stage the current
release. Live fetching requires the `live` or `research` extra and should follow a
successful synthetic run. Use `.[research,visualization]` for passing, modeling, and
story builds.

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` for functions and variables, `PascalCase` for test classes, and uppercase constants. Prefer `pathlib.Path`, small single-purpose functions, and explicit validation errors. Preserve game IDs as strings so leading zeros survive. No formatter or linter is configured; match the existing concise style and keep imports grouped with the standard library first.

## Testing Guidelines

Tests use the standard-library `unittest` framework. Add methods named `test_<behavior>` to `tests/test_pipeline.py`, or create `test_*.py` modules as coverage grows. Tests must be deterministic and offline: use invented fixtures, temporary directories, and mocks for failures. Cover validation, replay/idempotency, corrections, null handling, and failed-release preservation. The Parquet test may skip unless `.[columnar]` is installed.

## Commit & Pull Request Guidelines

Recent history uses short, imperative subjects such as `Add Knicks ETL foundation` and `Validate 2024-25 Knicks regular-season game count`. Keep each commit focused. Pull requests should explain the data-contract change, list verification commands and results, link relevant issues, and call out schema, coverage, or source-permission implications. Include screenshots only for rendered release previews.

## Data Safety & Configuration

Never commit credentials, `.env` files, virtual environments, raw third-party archives,
or generated datasets. Keep synthetic and live roots separate. Real basketball rows,
models, charts, and screenshots may exist only under ignored local roots, the approved
private research Bucket, or the approved private Space. Never put them in Git or the
synthetic dataset repository. Public promotion requires an explicit source-rights
review. Treat empty API responses as failures, not evidence of zero games. Read
`docs/CHECKPOINT.md`, `docs/RESEARCH_SCOPE.md`, and `docs/WEEKLY_RESEARCH.md` before
changing data boundaries, Hub publication, or release architecture.

## Current Checkpoint

`docs/CHECKPOINT.md` records the active GitHub/Hugging Face topology, verified commands,
implemented research domains, publication boundary, and next safe steps. Update it when
the architecture, remote state, supported seasons, or policy changes materially.

## Public NYK World Path

Read `docs/PUBLIC_ANALYTICS.md` before changing the public checkpoint. The public adapter
is `src/knicks_history/public_analytics.py`; it combines BALLDONTLIE `regular` and `ist`
partitions for the 82-game schedule, excludes the extra NBA Cup championship, and keeps
raw pages private. `scripts/validate_public_checkpoint.py` binds raw-page hashes, the
private source manifest, coverage, model artifacts, and the viewer/article bundles.
`huggingface/public-viewer/` is source for the exploration Space; narrative and methods
belong in the separate `../huggingface/NYKnicks_World/` repository.

Production publication is intentionally gated: `config/public-analytics.toml` must remain
disabled until a fresh source-rights review and owner approval. Offline fixtures are tests,
never production observations. Run the full Python suite, a fresh fixture checkpoint, the
validator, article build, embed checks, and viewer browser QA before activation. Do not
commit, push, create Hub resources, merge PRs, or alter visibility unless the user requests
that external action explicitly. Preserve the untracked user-owned `AWS.md`.
