# NYK World local research and synthetic Hub demonstrations

Maintained source for local research visualizations and synthetic Hugging Face
demonstrations lives here. Generated real-data Parquet, HTML, PNG, contracts, and
manifests belong under ignored `build/`; raw responses and local databases are never
uploaded. The repository does not publish a real-data Hugging Face dataset.

The local gallery produces eight coordinated views: season pulse, monthly fingerprint, game
profiles, result paths, opponent map, margin shape, opponent share, and matchup grid.
Every interactive D3Blocks artifact has a Matplotlib PNG fallback.

## Fast local review

The Make targets use `.venv-knicks` by default and never overwrite an existing build:

```bash
make test
make hf-fixture HF_PREVIEW=build/hf-review-001
make hf-validate HF_PREVIEW=build/hf-review-001
make hf-serve HF_PREVIEW=build/hf-review-001
```

Open `http://127.0.0.1:8000`. Use a new output path for each review so an old artifact
cannot be mistaken for the current source.

## Five-season passing methods lab

`fixtures/passing-demo.csv` is an invented five-season player-to-player contract, not
NBA data. Build its Sankey and Matplotlib fallback separately:

```bash
make passing-lab PASSING_PREVIEW=build/passing-review-001
python -m http.server 8001 --bind 127.0.0.1 --directory build/passing-review-001
```

For an authorized local research export, preserve the exact CSV columns and run
`python scripts/build_passing_lab.py --input path/to/export.csv --output build/passing-authorized --allow-authorized-real-data`.
The file must include a source URL and research basis on every row. The resulting HTML,
PNG, metadata, and source rows remain local and ignored; they are not Hub artifacts.

## Recreate the source release

Use Python 3.11–3.13 for the pinned visualization stack:

```bash
python -m pip install -e '.[visualization]'
python scripts/import_team_logs.py --start 2026 --end 2026 --root data/live
knicks build --root data/live --expected config/expected-live.csv --parquet
```

For a local 2025–26 review build:

```bash
python scripts/build_hf_release.py --root data/live --season 2025-26 \
  --output build/huggingface --allow-dirty
python scripts/validate_hf_release.py build/huggingface
python -m http.server 8000 --bind 127.0.0.1 --directory build/huggingface/space
```

`--allow-dirty` always produces a non-publishable local preview. Each payload has a closed
`release-manifest.json`; missing, modified, and unexpected files fail validation.

## Cumulative seasons

Repeat `--season` to build a cumulative local research dataset. Every selected season
must have `count_matches` coverage. A reviewed `config/teams/<season>.csv` takes
precedence; otherwise the builder uses `config/teams/common.csv`. `--space-season`
chooses the single season displayed by the local gallery.

## Public boundary

`config/huggingface-publication.toml` encodes a synthetic-only Hub policy. The
publisher independently reloads that policy and blocks real dataset or real-chart
payloads even if a generated manifest is edited. The real-data builder also marks its
payloads `local_research_only` and non-publishable. Synthetic fixture payloads can be
published only from a clean Git checkout with `--publishable`; the generated dataset
and Space identify themselves as invented demonstrations.

The synthetic Hub checkpoint uses two phases. First build and upload the dataset:

```bash
python scripts/build_hf_fixture_preview.py --output build/hf-synthetic-dataset --publishable
python scripts/publish_hf_release.py --input build/hf-synthetic-dataset --target dataset --execute
```

After that dataset change is accepted, rebuild from the same clean commit using the
exact 40-character dataset revision, then upload the Space:

```bash
python scripts/build_hf_fixture_preview.py --output build/hf-synthetic-space \
  --dataset-revision <dataset-commit> --publishable
python scripts/publish_hf_release.py --input build/hf-synthetic-space --target space --execute
```

Uploads are private and use Hub pull requests by default. Visibility changes, PR merge,
and replacement of a legacy Space remain explicit remote actions.

Public portfolio artifacts may include source code, schemas, documentation, invented
fixtures, and clearly labeled synthetic demonstrations. They may not include real rows,
real-data tables, real-data charts, or screenshots of those charts. A future change to
this boundary requires a source-specific license review and an explicit policy change;
it must not be inferred from another open-data program.
