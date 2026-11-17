# NYK_Learning

![Illustrative 3D view of generic game features](assets/feature-space-3d.png)

*Illustrative feature space only; values are examples, not historical Knicks statistics.*

Everything NY Knicks just because why not.

A Knicks data-engineering and ML learning project: historical statistics, structured game observations, reproducible datasets, and experiments grounded in explicit evidence.

## Current milestone

The current implementation is a **versioned basketball research system**:

- Preserve raw JSON responses and SHA-256 hashes.
- Validate game identifiers, counts, scores and source schemas.
- Join Knicks games to opponent scores.
- Build versioned CSV, SQLite and optional Parquet releases.
- Track season coverage and retain old snapshots when corrections arrive.
- Normalize private five-season player-passing edges with raw-response caching.
- Train interpretable win-probability and margin models with chronological backtests.
- Build a six-chapter, iframe-ready D3Blocks and Matplotlib research story.
- Test with invented games and mocked endpoints before live access.

No real historical dataset is included in Git. Fixtures and the reproducible public demo
are synthetic; authorized real rows, models, and visual artifacts stay in private
research storage and a private preview Space.

## Start here

Read [the local setup manual](docs/START_HERE.md).

From the repository root in your Python 3.11+ environment:

```bash
python3 -m venv .venv-knicks
source .venv-knicks/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
knicks ingest --input fixtures/league-demo.json --synthetic --season 2024-25 --root data/demo
knicks build --root data/demo --expected config/expected-demo.csv
```

Install `python -m pip install -e '.[columnar]'` and add `--parquet` to the build command for Parquet. GitHub Actions installs this extra and runs the same synthetic pipeline. Initial dependency ranges are not a fully locked environment; record exact versions after a successful local installation.

## Project map

| Directory | Purpose |
|---|---|
| `src/knicks_history` | ETL, validation, passing contracts, research storage, and models |
| `fixtures` | Explicitly synthetic teaching data |
| `tests` | Replay, corrections, nulls, integrity and failure tests |
| `config` | Expected fixture counts and historical review checklist |
| `sql` | Consumer queries and lagged feature example |
| `scripts` | Backfill, passing fetch, model training, release staging, and weekly orchestration |
| `huggingface` | Maintained dataset-card and static-Space source |
| `docs` | Setup and dataset card |
| `data` | Generated local snapshots/releases; ignored by Git |

## Verification

Run `python -m unittest discover -s tests -v` for the current offline contract suite and check Actions for the Parquet and visualization integration jobs. Generated historical data remains local; verify its release manifest and coverage before making completeness claims.

This repository is the public project page. A separate GitHub Pages website is not configured by this change.

## Historical team game data

The local season archive is generated and ignored by Git. To load regular seasons from 2017–18 through 2025–26 from the published team game logs source, install the optional columnar dependency and run:

```bash
python -m pip install -e '.[columnar]'
python scripts/import_team_logs.py --start 2018 --end 2026 --root data/live
knicks build --root data/live --expected config/expected-live.csv --parquet
```

The source uses the season ending year (`2018` means `2017-18`). The importer filters game IDs to regular-season games, preserves source provenance, and validates each season through the same archive pipeline as the NBA Stats adapter. Counts reflect NBA schedule changes, including 66 games in 2019–20 and 72 in 2020–21. Confirm source permissions and historical accuracy before redistributing exports.

## Local research warehouse and public demonstrations

The research builder turns immutable seasons and normalized passing edges into Parquet
tables, eight team views, a passing Sankey, a model lab, and static fallbacks. Real rows
and derived artifacts are private research material. For an authorized local build:

```bash
python -m pip install -e '.[research,visualization]'
python scripts/fetch_passing.py --season 2025-26 \
  --root data/research/player_passing --rights-basis '<documented private-research basis>'
python scripts/build_hf_release.py --root data/live --season 2025-26 \
  --passing data/research/player_passing/edges/2025-26.csv \
  --output build/huggingface --allow-dirty
python scripts/validate_hf_release.py build/huggingface
python -m http.server 8000 --directory build/huggingface/space
```

Generated `data/` and `build/` content stays ignored. The checked-in policy permits real
research releases only in the named private Hugging Face Bucket and real-data rendering
only in the named private Space. Public promotion is disabled and requires a separate,
source-specific rights review. See the [research scope](docs/RESEARCH_SCOPE.md) and
[Hugging Face guide](huggingface/README.md).

The standalone passing lab still defaults to invented data so its contract and Sankey
can be reviewed without network access or private rows.

## License

Original code and invented fixture: MIT, see [LICENSE](LICENSE). This does not grant redistribution rights for third-party NBA data. Document source permissions and historical coverage before using real extracts in local research.
