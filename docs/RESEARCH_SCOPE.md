# Local Research Scope

## Purpose

NYK Learning is a reproducible, local basketball research warehouse and an educational
data-engineering project. It may ingest a wider set of team, player, event, roster,
passing, and status data when access is authorized. Real source rows are not a public
dataset product.

The public portfolio demonstrates pipeline design with source code, contracts,
provenance controls, invented fixtures, and synthetic visualizations. A public artifact
must never be described as real when it is synthetic.

## Research Domains

The implemented base is one Knicks team-game row per game. Planned local extensions
are player box scores, effective-dated rosters, play-by-play events, player passing
edges, and dated injury or transaction events. `config/research-domains.toml` records
the grain, status, and ignored local root for every domain.

Use stable identifiers rather than names as keys. Preserve raw responses and retrieval
metadata under ignored `data/research/`; normalize into immutable releases; derive
features only from information available before the target event. Keep observations,
interpretations, confidence, and model targets separate.

## Public Boundary

Real research rows, extracts, Parquet or CSV tables, interactive charts, and screenshots
stay local unless a source-specific written license is added and reviewed in a future
scope change. The current policy allows only code, schemas, documentation, invented
fixtures, and synthetic demonstrations in public repositories or Hugging Face artifacts.

This is stricter than some open-data programs. For example, Citi Bike publishes trip
files under its own data-sharing license. That source-specific license is not evidence
that unrelated basketball data may be redistributed.

## Reproduction

A fresh clone reproduces the software and synthetic demonstrations. Reproducing local
real-data research requires the researcher to obtain each source independently, accept
its current terms, record provenance, and run the local import pipeline. The repository
does not bundle or mirror those source files.
