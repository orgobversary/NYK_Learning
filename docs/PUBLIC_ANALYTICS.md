# Public Analytics Checkpoints

This workflow turns completed Knicks seasons into one reviewable Hugging Face dataset and
two synchronized presentations: `nyk_world` for exploration and `NYKnicks_World` for the
read-along article. Production checkpoints use real BALLDONTLIE game records. Invented
fixtures remain offline and can never pass the production validator.

## One-time setup

1. Create a BALLDONTLIE API key and review its current terms. Do not paste the key into
   this repository, an issue, or a workflow input.
2. In the GitHub repository, create an Environment named `nyk-public-release`. Require a
   reviewer so a workflow dispatch cannot publish unattended.
3. Add Environment secrets `BALLDONTLIE_API_KEY` and `HF_TOKEN_NYK_PUBLISH`. Scope the
   Hugging Face token to write only the named private Bucket, dataset, and Spaces when
   possible.
4. Confirm the resource names and allowed payload in `config/public-analytics.toml`.
5. After the source and publication basis are accepted, change only
   `public_release_enabled` to `true`. Keep both automatic settings `false`.

## Offline rehearsal

```bash
make public-fixture
make public-validate
```

The rehearsal uses `fixtures/balldontlie-games-demo.json`, marks the manifest synthetic,
does not train models, and cannot be promoted. Remove `build/public-fixture` before rerunning
because checkpoints are intentionally write-once.

## Stage a real checkpoint

Run the **NYK public analytics checkpoint** workflow manually. Supply the completed-season
range, review date, reviewer name, and a short source-specific publication basis. The job:

1. fetches the official API and stores raw responses only in the private research Bucket;
2. combines `regular` and `ist` provider partitions for the 82-game schedule, excludes the
   extra NBA Cup championship, and enforces every season/phase count in
   `config/public-expected.csv`;
3. builds leak-resistant team features, expanding-window models, baselines, and metrics;
4. rejects credentials, provider IDs, private paths, synthetic rows, and incomplete file sets;
5. opens separate Hugging Face pull requests for the dataset, viewer, and article data.

The workflow does not merge pull requests or change visibility.

## Review and paired release

Compare the three pull requests to the same `release-manifest.json`. Verify checksums,
coverage, model-vs-baseline metrics, chart labels, mobile rendering, and the independent,
unofficial disclosure. Merge all three only after the review passes. Make the dataset and
both Spaces public together; otherwise leave all three private. Record the Hub commit URLs
and workflow run in the release notes.

If a source count changes, stop and investigate. Update `public-expected.csv` only with a
documented correction—never merely to make the workflow green. A later correction is a new
immutable checkpoint, not an overwrite of the private raw evidence.

The validator binds the public release to the private source-manifest digest, verifies every
referenced raw page checksum and byte count, reconciles `coverage.json` to `games.csv`, and
requires real checkpoints to contain both model artifacts. Hub uploads delete stale files
inside their reviewed target scope before adding the new closed checkpoint.
