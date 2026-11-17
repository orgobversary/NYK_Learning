# NYK World research and Hub operations

Maintained source for synthetic demonstrations and authenticated private research
previews lives here. Real-data Parquet, HTML, PNG, models, and manifests belong under
ignored `build/` or in the approved private research Bucket. Raw research is never put
in Git or the synthetic Hugging Face dataset repository.

The story produces eight coordinated team views, a five-season passing Sankey, a model
lab, and a methods chapter. Interactive D3Blocks artifacts have portable static fallbacks.

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

For an authorized research export, preserve the exact CSV columns and run
`python scripts/build_passing_lab.py --input path/to/export.csv --output build/passing-authorized --allow-authorized-real-data`.
The file must include a source URL and research basis on every row. The result remains
private and must follow `config/huggingface-publication.toml`.

## Recreate the source release

Use Python 3.11–3.13 for the pinned visualization stack:

```bash
python -m pip install -e '.[research,visualization]'
python scripts/import_team_logs.py --start 2026 --end 2026 --root data/live
knicks build --root data/live --expected config/expected-live.csv --parquet
```

For a local 2025–26 review build, first create or obtain an authorized normalized passing
CSV, then supply it explicitly:

```bash
python scripts/build_hf_release.py --root data/live --season 2025-26 \
  --passing data/research/player_passing/edges/2025-26.csv \
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

## Private research deployment

Stage a closed release only from a clean checkout, dry-run its Bucket sync, then execute
the upload after reviewing the manifest:

```bash
python scripts/stage_research_release.py --team-release data/live/releases/<id> \
  --passing data/research/player_passing --models build/models \
  --space build/huggingface/space --output-root build/research-staging
python scripts/sync_research_bucket.py --release build/research-staging/<id>
python scripts/sync_research_bucket.py --release build/research-staging/<id> --execute
```

The Bucket uses immutable `releases/<id>/` objects plus small verified registry pointers.
The private Space is the presentation tier, not the system of record. Weekly behavior,
credentials, rollback, and scheduling are documented in
[`docs/WEEKLY_RESEARCH.md`](../docs/WEEKLY_RESEARCH.md).

## Public boundary

`config/huggingface-publication.toml` separates synthetic publication from private real
research. The synthetic publisher blocks real rows and charts. The private research
sync accepts only closed, non-synthetic, non-public releases for the named private
Bucket. Automatic public promotion is disabled.

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
