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
- Normalize private five-season teammate edges from all-pass tracking or reconciled assists.
- Train interpretable win-probability and margin models with chronological backtests.
- Build a six-chapter, iframe-ready D3Blocks and Matplotlib research story.
- Test with invented games and mocked endpoints before live access.

No real historical dataset is included in Git. Fixtures and the reproducible public demo
are synthetic; authorized real rows, models, and visual artifacts stay in private
research storage and a private preview Space.

## Start here

Read [the local setup manual](docs/START_HERE.md).
Agents and maintainers resuming active work should also read the
[current project checkpoint](docs/CHECKPOINT.md) before editing either repository.

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
python scripts/import_team_logs.py --start 2018 --end 2026 --playoffs-year 2026 --root data/live
knicks build --root data/live --expected config/expected-live.csv --parquet
```

The source uses the season ending year (`2018` means `2017-18`). Regular-season imports
filter game IDs to the `002` prefix; repeatable `--playoffs-year` selections import the
`004` postseason partition. Both preserve source provenance and pass through the same
archive pipeline as the NBA Stats adapter. Counts reflect NBA schedule changes, including
66 games in 2019–20 and 72 in 2020–21. Confirm source permissions and historical accuracy
before redistributing exports.

### Revisioned NBA Stats lake with Ingestify

For private NBA.com research, `nba_api` remains the endpoint client and Ingestify adds a
local SQLite catalog, immutable raw-file revisions, checksums, and refresh-window caching.
The custom source deliberately supports only `LeagueGameLog`, requires explicit seasons,
keeps requests serial, and defers each network request until Ingestify decides the cached
dataset needs refreshing.

```bash
python -m pip install -e '.[lake]'
cp config/ingestify-nba.example.yaml config/ingestify-nba.local.yaml
# Edit the local copy's explicit season selectors and refresh_days first.
python scripts/archive_ingestify_nba.py \
  --config config/ingestify-nba.local.yaml \
  --root data/live
knicks build --root data/live --expected config/expected-live.csv --parquet
```

Both the lake and ETL outputs remain under ignored `data/` paths. The bridge first lets
Ingestify sync/cache each raw response, then sends those exact bytes through the existing
Knicks validation and release pipeline. It does not make NBA.com data public and does not
alter the separate BALLDONTLIE public checkpoint. Ingestify is an optional AGPL-licensed
dependency; review those obligations before distributing or hosting a combined service.

## Local research warehouse and public demonstrations

The research builder turns immutable seasons, the verified 2025–26 postseason, and
normalized teammate edges into Parquet tables, eight team views, a championship timeline,
a relationship Sankey, a model lab, and static fallbacks. Real rows and derived artifacts
are private research material. For an authorized local build:

```bash
python -m pip install -e '.[research,visualization]'
python scripts/fetch_assist_network.py \
  --season 2021-22 --season 2022-23 --season 2023-24 \
  --season 2024-25 --season 2025-26 --root data/research/player_passing \
  --rights-basis '<documented private-research basis>'
python scripts/build_hf_release.py --root data/live \
  --season 2021-22 --season 2022-23 --season 2023-24 \
  --season 2024-25 --season 2025-26 \
  --passing data/research/player_passing/assist_edges/five-season.csv \
  --output build/huggingface --allow-dirty
python scripts/validate_hf_release.py build/huggingface
python -m http.server 8000 --directory build/huggingface/space
```

Generated `data/` and `build/` content stays ignored. The checked-in policy permits real
research releases only in the named private Hugging Face Bucket and real-data rendering
only in the named private Space. Public promotion is disabled and requires a separate,
source-specific rights review. See the [research scope](docs/RESEARCH_SCOPE.md) and
[Hugging Face guide](huggingface/README.md).

The standalone passing lab still defaults to invented all-pass data. The observed fallback
is explicitly typed `assisted_made_basket`: it visualizes assister-to-scorer connections,
not every pass, and reconciles each season to the validated team-assist total.

## Public NYK World release path

The public path is source-specific and separate from the private NBA Stats research
warehouse. It fetches completed 2017–18 through 2025–26 regular seasons and playoff runs
from BALLDONTLIE, publishes only minimal game values plus derived aggregates, and evaluates
transparent team-level models with expanding-season windows and naive baselines.
Regular-season partitions combine the provider's `regular` and `ist` classifications while
excluding the extra NBA Cup championship game.

```bash
make public-fixture
make public-validate
```

That command pair is an offline contract rehearsal using invented input; it is not a public
data release. Real checkpoints run only through the manually approved GitHub Action, archive
raw responses in the private Hugging Face Bucket, and open review pull requests without
merging or changing visibility. The viewer and article are released as a matched pair against
the same checksum manifest. See [Public Analytics Checkpoints](docs/PUBLIC_ANALYTICS.md).

## License

Original code and invented fixture: MIT, see [LICENSE](LICENSE). This does not grant redistribution rights for third-party NBA data. Document source permissions and historical coverage before using real extracts in local research.
