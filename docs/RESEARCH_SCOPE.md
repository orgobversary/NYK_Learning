# Local Research Scope

## Purpose

NYK Learning is a reproducible, local basketball research warehouse and an educational
data-engineering project. It may ingest a wider set of team, player, event, roster,
passing, and status data when access is authorized. Real source rows are not a public
dataset product.

The public portfolio demonstrates pipeline design with source code, contracts,
provenance controls, invented fixtures, and synthetic visualizations. Authenticated
private previews may render real research outputs for review. A public artifact must
never be described as real when it is synthetic.

## Research Domains

The implemented base is one Knicks team-game row per game, with regular-season and
postseason partitions kept explicit. The 2025–26 playoff partition supports a validated
championship narrative; it is not mixed into regular-season features. Pregame team features and
observed assister-to-scorer edges are implemented; the all-pass tracking adapter remains
available but its upstream endpoint is currently unreachable. Player box scores, effective-dated rosters,
play-by-play events, and dated injury or transaction events remain planned.
`config/research-domains.toml` records
the grain, status, and ignored local root for every domain.

The optional private NBA Stats lake uses Ingestify for raw-file revisions and `nba_api` for
NBA.com transport. It is an operational cache and provenance layer, not a new data source or
a publication basis. Its adapter currently covers only league team-game logs; source calls
are serial, seasons are explicit, and cached raw bytes still pass through the existing ETL
validator before becoming a local release.

Use stable identifiers rather than names as keys. Preserve raw responses and retrieval
metadata under ignored `data/research/`; normalize into immutable releases; derive
features only from information available before the target event. Keep observations,
interpretations, confidence, and model targets separate.

## Public Boundary

Real research rows, extracts, Parquet or CSV tables, trained models, interactive charts,
and screenshots stay local or in the explicitly approved private Hugging Face Bucket
and private preview Space. They must not enter Git, the synthetic dataset repository,
or any public Hub artifact. Public promotion requires a source-specific written rights
review and an explicit policy change; it is never inferred from successful private use.

This is stricter than some open-data programs. For example, Citi Bike publishes trip
files under its own data-sharing license. That source-specific license is not evidence
that unrelated basketball data may be redistributed.

## Reproduction

A fresh clone reproduces the software and synthetic demonstrations. Reproducing private
real-data research requires the researcher to obtain each source independently, accept
its current terms, record provenance and a research basis, and run the import pipeline.
The repository does not bundle or mirror those source files.
