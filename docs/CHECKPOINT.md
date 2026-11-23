# Project Checkpoint

Date: 2026-11-22. This is the authoritative handoff for the current NYK World public
analytics and article work. Inspect live state before relying on resource status because
credentials, Hub commits, and branch state can change after this checkpoint.

## Start Here

The workspace root is not Git. It contains two independent repositories:

| Checkout | Remote | Responsibility |
|---|---|---|
| `NYK_Learning/` | `https://github.com/orgobversary/NYK_Learning.git` | ETL, source policy, validation, ML, checkpoint workflow, visual-viewer source |
| `huggingface/NYKnicks_World/` | `https://huggingface.co/spaces/obversarystudios/NYKnicks_World` | Read-along article, chapters, D3 embeds, article data placeholders |

Always run `git status --short --branch` in both repositories before editing. Current work
is intentionally uncommitted in both checkouts. Preserve it; do not reset, restore, commit,
push, or upload unless the user explicitly authorizes that action. `AWS.md` is an untracked,
user-owned guide and was deliberately left untouched.

## Product Split

- `obversarystudios/nyk_world` is the focused visual explorer. Its checked-in source is
  `huggingface/public-viewer/` in this repository.
- `obversarystudios/NYKnicks_World` is the editorial read-along article in the separate
  Space checkout.
- `obversarystudios/nyk-world-analytics` is the planned public dataset identity.
- `obversarystudios/nyk-world-research` remains the private raw-evidence Bucket.
- The older private synthetic `obversarystudios/nyk-world-data` must remain untouched.

Both Spaces remain private. The article work is committed and synchronized to the article
Space as `ba3ecde`. The Hugging Face CLI is authenticated as `obversarystudios`, but the new
analytics dataset has not been created because the public release gate remains disabled and
activation has not been approved. No real public rows, Hub pull requests, merges, visibility
changes, or public releases have occurred.

## Public Data Contract

Public v1 covers completed 2017–18 through 2025–26 seasons and every playoff run. It uses
BALLDONTLIE through `https://api.balldontlie.io/nba/v1/games`. The public adapter is
`src/knicks_history/public_analytics.py`.

For each regular season, fetch both provider types `regular` and `ist`. NBA Cup group and
knockout games remain in the 82-game schedule; exclude the additional Cup championship and
record that exclusion in the private source manifest. Fetch playoffs separately. Retry 408,
429, and transient 5xx/network failures, honor `Retry-After`, and throttle every request.
Exact season/phase expectations are in `config/public-expected.csv`.

Public artifacts contain minimal game values, hashed public keys, aggregates, pregame-only
features, and transparent expanding-window model outputs. They must never contain provider
IDs, credentials, raw responses, private paths, official logos, photography, or NBA Stats
research rows. Player passing remains out of public v1; the venue-to-result flow is explicitly
not a passing network.

## Evidence Chain

`scripts/build_public_checkpoint.py` builds an immutable checkpoint. Its validator must prove:

1. the public manifest binds the exact private source-manifest digest;
2. every referenced raw page exists and matches its SHA-256 and byte count;
3. raw-page provider types are complete (`regular` plus `ist`, or `playoffs`);
4. the raw directory contains no unreferenced pages;
5. coverage partitions match private source partitions and reconcile to `games.csv`;
6. manifest season and game totals reconcile to the public rows;
7. real checkpoints include prediction and metric artifacts;
8. viewer, article, and staged Space bundles exactly match the analytics payload;
9. secrets, provider IDs, private paths, and disallowed source markers are absent.

The manual workflow `.github/workflows/public-checkpoint.yml` writes raw evidence only to
the private Bucket and opens three Hub review PRs. Uploads delete stale files inside their
reviewed target scope before adding the new closed payload. The workflow never merges PRs
or changes visibility.

## Licensing

As of 2026-11-23, original software is licensed under AGPL-3.0-or-later. Original
documentation, article prose, visual designs, and invented teaching fixtures are licensed
under CC BY-SA 4.0. These licenses cover only material for which Obversary Studios owns the
relevant rights; provider data, trademarks, dependencies, and upstream template material
remain governed by their own terms. See `LICENSE` and `LICENSES/`.

## Policy Gates

`config/public-analytics.toml` is the controlling public policy and currently has
`public_release_enabled = false`. Keep it disabled until the owner completes a fresh source
and third-party-rights review, configures the protected `nyk-public-release` GitHub
Environment, and explicitly approves activation. Keep automatic merge and automatic
visibility changes disabled.

Production needs Environment secrets `BALLDONTLIE_API_KEY` and `HF_TOKEN_NYK_PUBLISH`.
Never request or record plaintext credentials in chat or Git. Read `docs/PUBLIC_ANALYTICS.md`
for the operator sequence. The older NBA Stats/private-research flow remains separate; also
read `docs/RESEARCH_SCOPE.md` and `config/huggingface-publication.toml` before changing it.

## Implemented Surfaces

- Private NBA Stats lake: `src/knicks_history/nba_client.py`,
  `src/knicks_history/ingestify_nba.py`, `scripts/archive_ingestify_nba.py`, and
  `config/ingestify-nba.example.yaml`. Ingestify revisions raw responses; `nba_api` performs
  deferred serial requests; the existing archive validator remains authoritative.
- Provider adapter, public tables, dataset card, coverage, and release manifest:
  `src/knicks_history/public_analytics.py`
- Logistic win and ridge margin models with chronological folds and dummy baselines:
  `src/knicks_history/public_modeling.py`
- Build and validation entry points: `scripts/build_public_checkpoint.py` and
  `scripts/validate_public_checkpoint.py`
- Manual review-only release workflow: `.github/workflows/public-checkpoint.yml`
- Dark responsive viewer: `huggingface/public-viewer/`
- Article source: `../huggingface/NYKnicks_World/app/src/content/article.mdx`
- NYK chapters and embeds: the article repo's
  `app/src/content/{chapters,embeds}/nyk-world/`

## Last Verified Offline State

The 2026-11-22 pre-activation revalidation established:

- `python -m unittest discover -s tests -v`: 78 tests passed, with four optional-lake tests
  skipped in the base environment.
- All 10 focused `nba_api` and Ingestify tests passed with the optional dependencies, and
  the installed `LeagueGameLog` constructor/schema contract matched the adapter.
- Fresh fixture checkpoint build and closed-manifest validation passed.
- A real-like offline checkpoint reconciled raw pages, provider types, coverage, models,
  bundles, and the private/public digest; raw tampering was rejected.
- Viewer JavaScript syntax passed.
- Article production build passed with 7 chapters, 14 headings, 13 components, and 3 routes.
- All five NYK embeds passed light/dark checks at 360 and 760 pixels.
- The staged viewer passed desktop 1440x1000 and full mobile 390-pixel browser review.
- `git diff --check` passed in both repositories.

The optional Ingestify integration is private-research infrastructure and does not change
the BALLDONTLIE-only public checkpoint contract. Ingestify is AGPL-licensed; distribution or
hosting of a combined service requires a separate license review.

The article build retains nonfatal upstream warnings about content-collection placement,
stale Browserslist data, and the missing sitemap `site` option.

## Revalidation Commands

From `NYK_Learning/`:

```bash
.venv-knicks/bin/python -m unittest discover -s tests -v
make public-fixture
make public-validate
node --check huggingface/public-viewer/app.js
git diff --check
```

`make public-fixture` is write-once at `build/public-fixture`; choose a fresh
`PUBLIC_FIXTURE` path or remove only that generated ignored directory before rerunning.

From `huggingface/NYKnicks_World/app/`:

```bash
npm ci
npm run build
npm run check:embed -- nyk-world/banner-signal.html --banner --widths 360,760
npm run check:embed -- nyk-world/season-pulse.html --data /data/nyk-world/games.csv --widths 360,760
npm run check:embed -- nyk-world/playoff-path.html --data /data/nyk-world/games.csv --widths 360,760
npm run check:embed -- nyk-world/opponent-gravity.html --data /data/nyk-world/games.csv --widths 360,760
npm run check:embed -- nyk-world/model-signal.html --data /data/nyk-world/model_predictions.csv --widths 360,760
```

## Next Safe Phase: Credential-Backed Activation

1. Recheck both worktrees and review the complete diffs.
2. Reconfirm the active Hugging Face account and scoped Environment token without exposing it.
3. Create/confirm the private `obversarystudios/nyk-world-analytics` dataset.
4. Review current BALLDONTLIE terms and document the review date, reviewer, and basis.
5. Set only `public_release_enabled = true` after explicit owner approval.
6. Commit and push the two repositories only when explicitly authorized.
7. Dispatch the protected workflow and investigate any coverage discrepancy; never weaken
   expected counts merely to obtain a green run.
8. Review the dataset, viewer, and article-data Hub PRs against the same manifest.
9. Merge and change visibility only as one coordinated, explicitly approved release.

Update this checkpoint whenever architecture, source semantics, policy, remote state,
credentials, verified scope, or deployment status changes materially.
