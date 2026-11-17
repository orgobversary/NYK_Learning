# Project Checkpoint

Date: 2026-11-17. The commit containing this file is the NYK World V2 private-research
checkpoint for future work in this directory.

## Repository Topology

- GitHub source: `orgobversary/NYK_Learning`, public, default branch `main`.
- Hugging Face Space: `obversarystudios/nyk_world`, private at this checkpoint.
- Hugging Face dataset: `obversarystudios/nyk-world-data`, private synthetic fixture.
- Hugging Face Bucket: `obversarystudios/nyk-world-research`, private research releases.
- Local real data: ignored `data/`; never commit or move into the synthetic dataset.

## Implemented

- Replayable team-game ETL with coverage, checksums, corrections, and Parquet exports.
- Nine-season team backfill contract and exact per-season coverage checks.
- Eight team charts, a five-season passing Sankey, and Matplotlib fallbacks.
- Private NBA Stats passing adapter with pacing, retries, caching, and provenance.
- Interpretable win and margin models with time-aware validation, dummy baselines,
  uncertainty intervals, model cards, coefficients, and predictions.
- Six-chapter dark story UI, closed manifests, responsive browser checks, immutable
  private release staging, Bucket sync, and weekly HF Job orchestration.

## Research Boundary

Read `docs/RESEARCH_SCOPE.md`, `config/research-domains.toml`, and
`config/huggingface-publication.toml`. Real team, passing, feature, model, and rendered
artifacts are allowed only in ignored local roots, the approved private Bucket, and the
approved private Space. Public promotion is disabled. Changing that requires an explicit
source-rights review and policy edit.

## Verification

```bash
make test
python scripts/build_hf_fixture_preview.py --output build/hf-fixture
python scripts/validate_hf_release.py build/hf-fixture
make passing-lab PASSING_PREVIEW=build/passing-fixture
```

CI additionally browser-tests all eight gallery tabs and the passing Sankey. Builders
refuse to overwrite existing outputs; select a new ignored output directory per review.
The Hub release guide documents both synthetic publication and private research flows.
Private research releases use closed manifests and immutable Bucket paths; registry
pointers move only after verification. A successful private preview is not public-release
approval.

## Next Safe Work

1. Review the private preview and model card before any public portfolio embedding.
2. Monitor the weekly schedule, Bucket growth, no-op behavior, and source availability.
3. Add player box-score, roster, and play-by-play contracts only behind the same boundary.
4. Keep portfolio copy explicit about synthetic, observed, modeled, and unavailable data.
5. Re-run tests, release validation, and browser QA before every source or policy change.
