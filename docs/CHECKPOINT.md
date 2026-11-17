# Project Checkpoint

Date: 2026-11-17. The commit containing this file is the research-scope and synthetic
Hub checkpoint for future work in this directory.

## Repository Topology

- GitHub source: `orgobversary/NYK_Learning`, public, default branch `main`.
- Hugging Face Space: `obversarystudios/nyk_world`, private at this checkpoint.
- Hugging Face dataset: `obversarystudios/nyk-world-data`, private synthetic fixture.
- Local real data: ignored `data/`; never upload, commit, or screenshot for publication.

## Implemented

- Replayable team-game ETL with coverage, checksums, corrections, and Parquet exports.
- Local 2025-26 research release validated at 82 regular-season games.
- Eight D3Blocks charts with eight Matplotlib fallbacks.
- Five-season synthetic passer-to-receiver Sankey and authorized local CSV contract.
- Closed release manifests, browser checks, synthetic-only Hub policy, and Make targets.

## Research Boundary

Read `docs/RESEARCH_SCOPE.md` and `config/research-domains.toml`. Real team, player,
play-by-play, passing, roster, injury, transaction, feature, and model data stays local.
Only code, schemas, documentation, invented fixtures, and clearly labeled synthetic
demonstrations may be published. Changing this requires an explicit reviewed policy edit.

## Verification

```bash
make test
python scripts/build_hf_fixture_preview.py --output build/hf-fixture
python scripts/validate_hf_release.py build/hf-fixture
make passing-lab PASSING_PREVIEW=build/passing-fixture
```

CI additionally browser-tests all eight gallery tabs and the passing Sankey. Builders
refuse to overwrite existing outputs; select a new ignored output directory per review.
The Hub release guide documents the clean two-phase synthetic dataset/Space update.
Dataset manifests remain invariant between phases; only the Space manifest records the
pinned dataset revision and Space publication readiness.

## Next Safe Work

1. Implement player box-score and effective-dated roster contracts locally.
2. Add authorized local play-by-play and passing adapters without network calls in tests.
3. Add chronological research notebooks or scripts that consume immutable releases.
4. Keep portfolio copy explicit about synthetic versus observed results.
5. Re-run tests, payload validation, and both browser suites before any remote update.
