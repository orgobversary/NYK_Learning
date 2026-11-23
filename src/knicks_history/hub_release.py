"""Build and validate reviewable Hugging Face dataset and Space payloads."""
import csv
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

RELEASE_ID = re.compile(r"[0-9TZ]+-[a-f0-9]{8}")
HUB_COMMIT = re.compile(r"[a-f0-9]{40}")
PERCENT_FIELDS = (("fg_pct", "fgm", "fga"), ("fg3_pct", "fg3m", "fg3a"),
                  ("ft_pct", "ftm", "fta"))
PREGAME_AVERAGES = ("pts", "opponent_pts", "point_margin", "reb", "ast", "tov")
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md"}
FORBIDDEN_MARKERS = ("/var/home/", "file:///home/", "file:///var/", "gumroad",
                     "google-analytics", "googletagmanager")
FORBIDDEN_PATTERNS = (re.compile(r"sk-[a-z0-9_-]{16,}", re.IGNORECASE),)
DATASET_ID = "obversarystudios/nyk-world-data"
MANIFEST_NAME = "release-manifest.json"
CHARTS = (
    {"slug": "season-pulse", "label": "Season pulse",
     "description": "Scoring and prior-five-game form over the season.",
     "alt": "Line chart comparing Knicks points, opponent points, and prior-five-game scoring."},
    {"slug": "monthly-fingerprint", "label": "Monthly fingerprint",
     "description": "Monthly metrics normalized within the selected season.",
     "alt": "Matrix of standardized monthly scoring, shooting, rebounding, assists, turnovers, and win rate."},
    {"slug": "game-profiles", "label": "Game profiles",
     "description": "Three-point volume and accuracy, colored by result and sized by rebounds.",
     "alt": "Scatter plot of three-point attempts and accuracy for each game."},
    {"slug": "result-paths", "label": "Result paths",
     "description": "Game counts flowing from season to venue and final result.",
     "alt": "Bar chart summarizing home and away wins and losses."},
    {"slug": "opponent-map", "label": "Opponent map",
     "description": "A chord view of home and away games connected to each opponent.",
     "alt": "Network chart connecting home and away games to opponents."},
    {"slug": "margin-shape", "label": "Margin shape",
     "description": "The distribution of point margins at home and away.",
     "alt": "Violin plot comparing home and away point-margin distributions."},
    {"slug": "opponent-share", "label": "Opponent share",
     "description": "Schedule share by opponent; rectangle area represents games played.",
     "alt": "Treemap showing the number of games played against each opponent."},
    {"slug": "matchup-grid", "label": "Matchup grid",
     "description": "Win percentage against each opponent, split by home and away games.",
     "alt": "Matrix of win percentage by opponent and venue."},
)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_ratio(made, attempted):
    if made is None or attempted in (None, 0):
        return None
    return round(made / attempted, 6)


def mean(values):
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 6) if values else None


def require_visualization_python():
    if not ((3, 11) <= sys.version_info[:2] < (3, 14)):
        raise RuntimeError("The pinned visualization stack requires Python 3.11-3.13")


def repository_state(repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[2])
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    return {"git_sha": sha, "git_dirty": bool(status)}


def load_team_dimension(path):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    teams = {}
    for row in rows:
        team_id = str(row["team_id"])
        if team_id in teams:
            raise ValueError(f"Duplicate team ID: {team_id}")
        if not re.fullmatch(r"[A-Z0-9]{2,4}", row["team_abbrev"]):
            raise ValueError(f"Invalid team abbreviation: {row['team_abbrev']}")
        teams[team_id] = dict(row)
    if len(teams) != 30:
        raise ValueError(f"Expected 30 NBA teams, found {len(teams)}")
    return teams


def resolve_team_dimension(teams_dir, season):
    teams_dir = Path(teams_dir)
    specific = teams_dir / f"{season}.csv"
    common = teams_dir / "common.csv"
    if specific.exists():
        return specific
    if common.exists():
        return common
    raise FileNotFoundError(f"No team dimension for {season} and no common fallback")


def load_current_release(root, seasons):
    root = Path(root)
    seasons = [seasons] if isinstance(seasons, str) else list(dict.fromkeys(seasons))
    release_id = (root / "CURRENT").read_text(encoding="utf-8").strip()
    if not RELEASE_ID.fullmatch(release_id):
        raise ValueError("Malformed CURRENT release ID")
    release = root / "releases" / release_id
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not False:
        raise ValueError("The historical Hub release must not use synthetic data")
    with (release / "team_games.csv").open(newline="", encoding="utf-8") as stream:
        all_rows = list(csv.DictReader(stream))
    with (release / "coverage.csv").open(newline="", encoding="utf-8") as stream:
        all_coverage = list(csv.DictReader(stream))
    selected = {}
    for season in seasons:
        rows = [row for row in all_rows if row["season"] == season and
                row.get("season_type") == "Regular Season"]
        coverage = [row for row in all_coverage if row["season"] == season and
                    row["season_type"] == "Regular Season"]
        if not rows:
            raise ValueError(f"Release has no {season} rows")
        if len(coverage) != 1:
            raise ValueError(f"Expected one coverage row for {season}")
        evidence = coverage[0]
        if evidence.get("status") != "count_matches":
            raise ValueError(f"Coverage is not promoted for {season}: {evidence.get('status')}")
        expected = int(evidence["expected_games"])
        if len(rows) != expected:
            raise ValueError(f"Expected {expected} {season} games, found {len(rows)}")
        if int(evidence.get("missing_opponent_rows") or 0):
            raise ValueError(f"Coverage has missing opponents for {season}")
        selected[season] = {"rows": rows, "coverage": evidence}
    return release, manifest, selected


def load_playoff_partition(release, season):
    """Load one coverage-verified postseason partition from an immutable release."""
    release = Path(release)
    with (release / "team_games.csv").open(newline="", encoding="utf-8") as stream:
        rows = [row for row in csv.DictReader(stream)
                if row["season"] == season and row["season_type"] == "Playoffs"]
    with (release / "coverage.csv").open(newline="", encoding="utf-8") as stream:
        coverage = [row for row in csv.DictReader(stream)
                    if row["season"] == season and row["season_type"] == "Playoffs"]
    if len(coverage) != 1 or coverage[0].get("status") != "count_matches":
        raise ValueError(f"Playoff coverage is not promoted for {season}")
    expected = int(coverage[0]["expected_games"])
    if len(rows) != expected:
        raise ValueError(f"Expected {expected} {season} playoff games, found {len(rows)}")
    if int(coverage[0].get("missing_opponent_rows") or 0):
        raise ValueError(f"Playoff coverage has missing opponents for {season}")
    return rows, coverage[0]


def _integer(value):
    return None if value in (None, "") else int(value)


def enrich_games(rows, teams):
    enriched, seen = [], set()
    for source in rows:
        key = (source["season"], source["season_type"], source["game_id"], source["team_id"])
        if key in seen:
            raise ValueError(f"Duplicate game fact: {key}")
        seen.add(key)
        if not re.fullmatch(r"\d{10}", source["game_id"]):
            raise ValueError("game_id must remain a ten-digit string")
        row = dict(source)
        for field in ("team_id", "pts", "opponent_id", "opponent_pts", "point_margin",
                      "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb",
                      "reb", "ast", "stl", "blk", "tov", "pf"):
            row[field] = _integer(row.get(field))
        opponent_id = str(row["opponent_id"])
        if opponent_id not in teams:
            raise ValueError(f"Unresolved opponent ID: {opponent_id}")
        row["team_id"], row["opponent_id"] = str(row["team_id"]), opponent_id
        row["opponent_name"] = teams[opponent_id]["team_name"]
        row["opponent_abbrev"] = teams[opponent_id]["team_abbrev"]
        for name, made, attempted in PERCENT_FIELDS:
            row[name] = safe_ratio(row[made], row[attempted])
        enriched.append(row)
    return sorted(enriched, key=lambda row: (row["game_date"], row["game_id"]))


def _paired_ratio(rows, made, attempted):
    pairs = [(row[made], row[attempted]) for row in rows
             if row[made] is not None and row[attempted] is not None]
    return safe_ratio(sum(x for x, _ in pairs), sum(y for _, y in pairs)) if pairs else None


def build_pregame_features(games, window=5):
    output = []
    for index, game in enumerate(games):
        previous, recent = games[:index], games[max(0, index - window):index]
        row = {"season": game["season"], "game_id": game["game_id"],
               "game_date": game["game_date"], "opponent_id": game["opponent_id"],
               "opponent_abbrev": game["opponent_abbrev"], "venue_side": game["venue_side"],
               "games_played_before": len(previous), "history_games": len(recent),
               "season_to_date_win_pct": safe_ratio(sum(x["wl"] == "W" for x in previous),
                                                      len(previous)),
               "target_win": 1 if game["wl"] == "W" else 0,
               "target_point_margin": game["point_margin"]}
        for field in PREGAME_AVERAGES:
            row[f"prior_5_{field}"] = mean([item[field] for item in recent])
        for name, made, attempted in PERCENT_FIELDS:
            row[f"prior_5_{name}"] = _paired_ratio(recent, made, attempted)
        output.append(row)
    return output


def build_monthly_summary(games):
    groups = defaultdict(list)
    for game in games:
        groups[game["game_date"][:7]].append(game)
    output = []
    for month, rows in sorted(groups.items()):
        output.append({"season": rows[0]["season"], "month": month, "games": len(rows),
                       "win_pct": safe_ratio(sum(x["wl"] == "W" for x in rows), len(rows)),
                       "pts_per_game": mean([x["pts"] for x in rows]),
                       "opponent_pts_per_game": mean([x["opponent_pts"] for x in rows]),
                       "mean_margin": mean([x["point_margin"] for x in rows]),
                       "fg_pct": _paired_ratio(rows, "fgm", "fga"),
                       "fg3_pct": _paired_ratio(rows, "fg3m", "fg3a"),
                       "ft_pct": _paired_ratio(rows, "ftm", "fta"),
                       "reb_per_game": mean([x["reb"] for x in rows]),
                       "ast_per_game": mean([x["ast"] for x in rows]),
                       "tov_per_game": mean([x["tov"] for x in rows])})
    return output


def build_result_paths(games):
    edges, season = defaultdict(int), games[0]["season"]
    for game in games:
        venue, result = game["venue_side"].title(), "Win" if game["wl"] == "W" else "Loss"
        edges[(season, venue)] += 1
        edges[(venue, result)] += 1
    return [{"source": a, "target": b, "weight": weight}
            for (a, b), weight in sorted(edges.items())]


def build_playoff_journey(games):
    """Validate and narrate the Knicks' 2026 four-series championship run."""
    games = sorted(games, key=lambda row: (row["game_date"], row["game_id"]))
    expected = (
        ("First Round", "ATL", 4, 2),
        ("East Semifinals", "PHI", 4, 0),
        ("East Finals", "CLE", 4, 0),
        ("NBA Finals", "SAS", 4, 1),
    )
    if len(games) != 19 or any(row["season"] != "2025-26" or
                               row["season_type"] != "Playoffs" for row in games):
        raise ValueError("The championship story requires 19 verified 2025-26 playoff games")
    groups = []
    for game in games:
        if not groups or groups[-1][0]["opponent_abbrev"] != game["opponent_abbrev"]:
            groups.append([])
        groups[-1].append(game)
    observed = tuple((label, rows[0]["opponent_abbrev"],
                      sum(row["wl"] == "W" for row in rows),
                      sum(row["wl"] == "L" for row in rows))
                     for (label, _, _, _), rows in zip(expected, groups))
    if len(groups) != len(expected) or observed != expected:
        raise ValueError(f"Unexpected 2026 playoff series path: {observed}")
    if sum(row["point_margin"] for row in games) != 283:
        raise ValueError("The playoff point differential does not reconcile to +283")
    streak = best = cumulative_margin = cumulative_wins = 0
    output, series = [], []
    offset = 0
    for series_index, ((label, opponent, wins, losses), rows) in enumerate(zip(expected, groups), 1):
        series.append({"round": label, "opponent": opponent,
                       "opponent_name": rows[0]["opponent_name"], "wins": wins,
                       "losses": losses, "games": len(rows), "start_game": offset + 1,
                       "end_game": offset + len(rows)})
        for series_game, row in enumerate(rows, 1):
            cumulative_margin += row["point_margin"]
            cumulative_wins += row["wl"] == "W"
            streak = streak + 1 if row["wl"] == "W" else 0
            best = max(best, streak)
            output.append({"game": offset + series_game, "series_game": series_game,
                           "series_index": series_index, "round": label,
                           "opponent": opponent, "date": row["game_date"],
                           "venue": row["venue_side"], "result": row["wl"],
                           "points": row["pts"], "opponent_points": row["opponent_pts"],
                           "margin": row["point_margin"],
                           "cumulative_margin": cumulative_margin,
                           "cumulative_wins": cumulative_wins})
        offset += len(rows)
    if best != 13 or output[-1]["points"] != 94 or output[-1]["opponent_points"] != 90:
        raise ValueError("The title-run milestones do not reconcile")
    return {"games": output, "series": series, "wins": cumulative_wins,
            "losses": len(games) - cumulative_wins, "point_differential": cumulative_margin,
            "longest_win_streak": best,
            "milestone": {"label": "The Hand of OG", "game": 18,
                          "detail": "Game 4 Finals comeback from 29 points down",
                          "source": "https://www.nba.com/news/season-review-2025-26"}}


def build_opponent_views(games):
    """Return compact opponent aggregates shared by interactive and static charts."""
    schedule, records = defaultdict(int), defaultdict(list)
    for game in games:
        venue = game["venue_side"].title()
        opponent = game["opponent_abbrev"]
        schedule[(venue, opponent)] += 1
        records[(opponent, venue)].append(1 if game["wl"] == "W" else 0)
    chord = [{"source": venue, "target": opponent, "weight": count}
             for (venue, opponent), count in sorted(schedule.items())]
    opponents = sorted({game["opponent_abbrev"] for game in games})
    grid = [{"opponent": opponent,
             "home": mean(records.get((opponent, "Home"), [])),
             "away": mean(records.get((opponent, "Away"), [])),
             "overall": mean(records.get((opponent, "Home"), []) +
                             records.get((opponent, "Away"), []))}
            for opponent in opponents]
    totals = [{"source": "Opponents", "target": opponent,
               "weight": sum(count for (venue, name), count in schedule.items()
                             if name == opponent)}
              for opponent in opponents]
    return chord, grid, totals


def load_publication_gate(path):
    with Path(path).open("rb") as stream:
        gate = tomllib.load(stream)
    reviewed = gate.get("redistribution_reviewed") is True
    required = ("reviewed_by", "reviewed_at", "basis", "dataset_license")
    complete = reviewed and all(str(gate.get(key, "")).strip() for key in required)
    if reviewed:
        try:
            date.fromisoformat(str(gate.get("reviewed_at", "")))
        except ValueError as exc:
            raise ValueError("reviewed_at must be an ISO date") from exc
        if not complete:
            raise ValueError("A reviewed publication gate must complete every required field")
    gate["complete"] = complete
    return gate


def public_payload_allowed(gate, synthetic):
    """Enforce the research/public boundary independently of generated flags."""
    if gate.get("research_only") is not True:
        return False
    if gate.get("hub_publication_enabled") is not True:
        return False
    if gate.get("real_data_distribution_allowed") is not False:
        return False
    return synthetic is True and gate.get("synthetic_demo_distribution_allowed") is True


def publication_status(gate_complete, source_dirty, dataset_revision,
                       builder_dirty=False, commits_match=True, force_preview=False):
    dataset_ready = (gate_complete and not source_dirty and not builder_dirty and
                     commits_match and not force_preview)
    space_ready = dataset_ready and HUB_COMMIT.fullmatch(dataset_revision) is not None
    return {"dataset_publishable": dataset_ready, "space_publishable": space_ready,
            "publishable": space_ready}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_parquet(path, rows):
    try:
        import polars as pl
    except ImportError as exc:
        raise RuntimeError("Install the visualization extra to export Parquet") from exc
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(path, compression="zstd")


def _dataset_readme(seasons, rows, license_name):
    labels = ", ".join(seasons)
    return f'''---
license: {license_name}
pretty_name: NYK Local Research Tables
configs:
  - config_name: games
    data_files: [{{split: regular_season, path: data/games/*.parquet}}]
    default: true
  - config_name: pregame_features
    data_files: [{{split: regular_season, path: data/pregame_features/*.parquet}}]
  - config_name: monthly_summary
    data_files: [{{split: regular_season, path: data/monthly_summary/*.parquet}}]
  - config_name: teams
    data_files: [{{split: regular_season, path: data/teams/*.parquet}}]
tags: [basketball, data-engineering, time-series, feature-engineering]
---

# NYK Local Research Tables

A versioned local research dataset for Knicks regular seasons {labels}. This cumulative
release contains {rows} completed team games and is produced by the NYK Learning ETL.
It is a local artifact, not a redistributable Hugging Face dataset.

`games` contains normalized facts; `pregame_features` contains prior-game rolling
features with explicit `target_*` outcomes; `monthly_summary` supports visualizations;
and `teams` contains reviewed season-specific labels. Machine-readable grain, keys,
types, nullability, feature timing, provenance, and SHA-256 inventory are under
`metadata/`. Game IDs remain text and features use at most five prior games.

Original software is licensed under AGPL-3.0-or-later. `license: {license_name}` records
the data license selected for this local payload; the software license does not grant
rights to third-party basketball facts. Do not upload this payload. It contains no player
or tracking data, causal claims, predictive model, or official league artwork.
'''


def _synthetic_dataset_readme(season, rows):
    return f'''---
license: cc-by-sa-4.0
pretty_name: NYK World Synthetic Demo
configs:
  - config_name: games
    data_files: [{{split: synthetic, path: data/games/*.parquet}}]
    default: true
  - config_name: pregame_features
    data_files: [{{split: synthetic, path: data/pregame_features/*.parquet}}]
  - config_name: monthly_summary
    data_files: [{{split: synthetic, path: data/monthly_summary/*.parquet}}]
  - config_name: teams
    data_files: [{{split: synthetic, path: data/teams/*.parquet}}]
tags: [synthetic, basketball, data-engineering, visualization]
---

# NYK World Synthetic Demo

An invented {rows}-game {season} fixture used to demonstrate the NYK Learning ETL,
contracts, D3Blocks gallery, and Matplotlib fallbacks. Every team label, score, and game
fact in this dataset is synthetic. It is not NBA data and must not be used for factual
basketball analysis. Original software is licensed under AGPL-3.0-or-later, and this
invented teaching fixture is licensed under CC BY-SA 4.0.
'''


def _space_readme(season, revision, dataset_id=None):
    dataset_metadata = f"datasets:\n  - {dataset_id}\n" if dataset_id else ""
    dataset_note = (f" Synthetic data is pinned to [{dataset_id} revision `{revision}`]"
                    f"(https://huggingface.co/datasets/{dataset_id}/tree/{revision})."
                    if dataset_id else "")
    return f'''---
title: NYK World
emoji: 🏀
colorFrom: blue
colorTo: indigo
sdk: static
app_file: index.html
pinned: true
license: agpl-3.0
{dataset_metadata}short_description: Interactive {season} Knicks team-game visualizations
disable_embedding: false
---

# NYK World

A six-chapter, neon-arena data story with eight team-game D3Blocks views, Matplotlib
fallbacks, a passing-network chapter, and an inspectable model-signal chapter. Snapshot
identifier: `{revision}`. Real research releases and their authenticated previews remain
private until explicit review.{dataset_note} Synthetic releases are demonstrations only.
'''


def _copy_space_source(source, destination):
    source, destination = Path(source), Path(destination)
    shutil.copytree(source / "styles", destination / "styles")
    shutil.copytree(source / "scripts", destination / "scripts")
    return (source / "index.template.html").read_text(encoding="utf-8")


def _generate_previews(games, features, monthly, destination):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/nyk-world-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.lines import Line2D
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    plt.style.use("dark_background")
    blue, orange, muted = "#55a7e0", "#f28c38", "#9ab0c3"
    dates = [datetime.fromisoformat(x["game_date"]) for x in games]
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    ax.plot(dates, [x["pts"] for x in games], color=blue, label="Knicks")
    ax.plot(dates, [x["opponent_pts"] for x in games], color=orange, label="Opponent")
    ax.plot(dates, [x["prior_5_pts"] for x in features], color=muted, linestyle="--", label="Prior 5")
    ax.set(title="Season pulse", ylabel="Points"); ax.legend(frameon=False, ncol=3)
    fig.savefig(destination / "season-pulse.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    metrics = ("win_pct", "pts_per_game", "mean_margin", "fg_pct", "fg3_pct",
               "reb_per_game", "ast_per_game", "tov_per_game")
    values = np.array([[row[name] for name in metrics] for row in monthly], dtype=float)
    means, stds = np.nanmean(values, axis=0), np.nanstd(values, axis=0)
    values = np.divide(values - means, stds, out=np.zeros_like(values), where=stds != 0)
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    image = ax.imshow(values, cmap="coolwarm", aspect="auto", vmin=-2, vmax=2)
    ax.set(yticks=range(len(monthly)), yticklabels=[x["month"] for x in monthly],
           xticks=range(len(metrics)), xticklabels=metrics, title="Monthly fingerprint")
    ax.tick_params(axis="x", rotation=35); fig.colorbar(image, ax=ax, label="Within-season z-score")
    fig.savefig(destination / "monthly-fingerprint.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    colors = [blue if x["wl"] == "W" else orange for x in games]
    ax.scatter([x["fg3a"] for x in games], [x["fg3_pct"] for x in games],
               s=[max(x["reb"], 1) * 2 for x in games], c=colors, alpha=.72)
    ax.set(title="Game profiles", xlabel="Three-point attempts", ylabel="Three-point percentage")
    ax.legend(handles=[Line2D([], [], marker="o", linestyle="", color=blue, label="Win"),
                       Line2D([], [], marker="o", linestyle="", color=orange, label="Loss")], frameon=False)
    fig.savefig(destination / "game-profiles.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    counts = defaultdict(int)
    for game in games: counts[(game["venue_side"].title(), "Win" if game["wl"] == "W" else "Loss")] += 1
    labels = [f"{v} → {r}" for v in ("Home", "Away") for r in ("Win", "Loss")]
    fig, ax = plt.subplots(figsize=(9, 5), layout="constrained")
    ax.barh(labels, [counts[tuple(x.split(" → "))] for x in labels], color=[blue, orange, blue, orange])
    ax.set(title="Result paths", xlabel="Games")
    fig.savefig(destination / "result-paths.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    chord, grid, totals = build_opponent_views(games)
    opponents = [row["target"] for row in totals]
    home = [next((row["weight"] for row in chord
                  if row["source"] == "Home" and row["target"] == opponent), 0)
            for opponent in opponents]
    away = [next((row["weight"] for row in chord
                  if row["source"] == "Away" and row["target"] == opponent), 0)
            for opponent in opponents]
    fig, ax = plt.subplots(figsize=(12, 6), layout="constrained")
    ax.bar(opponents, home, color=blue, label="Home")
    ax.bar(opponents, away, bottom=home, color=orange, label="Away")
    ax.set(title="Opponent map", ylabel="Games"); ax.tick_params(axis="x", rotation=55)
    ax.legend(frameon=False)
    fig.savefig(destination / "opponent-map.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    margin_groups = [[x["point_margin"] for x in games if x["venue_side"] == venue]
                     for venue in ("home", "away")]
    parts = ax.violinplot(margin_groups, showmeans=True, showextrema=True)
    for body, color in zip(parts["bodies"], (blue, orange)): body.set_facecolor(color)
    ax.axhline(0, color=muted, linewidth=1); ax.set_xticks((1, 2), ("Home", "Away"))
    ax.set(title="Margin shape", ylabel="Point margin")
    fig.savefig(destination / "margin-shape.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 6), layout="constrained")
    ax.bar(opponents, [row["weight"] for row in totals], color=blue)
    ax.set(title="Opponent share", ylabel="Games"); ax.tick_params(axis="x", rotation=55)
    fig.savefig(destination / "opponent-share.png", dpi=150, facecolor="#07111d"); plt.close(fig)
    values = np.array([[row["home"], row["away"], row["overall"]] for row in grid], dtype=float)
    fig, ax = plt.subplots(figsize=(8, max(5, len(grid) * .32)), layout="constrained")
    image = ax.imshow(values, cmap="RdYlBu", aspect="auto", vmin=0, vmax=1)
    ax.set(yticks=range(len(grid)), yticklabels=[row["opponent"] for row in grid],
           xticks=(0, 1, 2), xticklabels=("Home", "Away", "Overall"), title="Matchup grid")
    fig.colorbar(image, ax=ax, label="Win percentage")
    fig.savefig(destination / "matchup-grid.png", dpi=150, facecolor="#07111d"); plt.close(fig)


def _normalize_javascript_assets(destination):
    """Convert D3Blocks UTF-16 bundles to Hub-compatible UTF-8 text."""
    for path in Path(destination).glob("*.js"):
        raw = path.read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16").replace("\r\n", "\n").replace("\r", "\n")
            path.write_text(text, encoding="utf-8", newline="\n")


def _generate_d3(games, features, monthly, paths, destination):
    import numpy as np
    import pandas as pd
    from d3blocks import D3Blocks
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    d3 = D3Blocks(support=False, verbose="error")
    timeline = pd.DataFrame({"date": [x["game_date"] for x in games],
                             "Knicks points": [x["pts"] for x in games],
                             "Opponent points": [x["opponent_pts"] for x in games],
                             "Prior 5 points": [x["prior_5_pts"] for x in features]})
    d3.timeseries(timeline, datetime="date", dt_format="%Y-%m-%d", title="Season Pulse",
                  filepath=str(destination / "season-pulse.html"), showfig=False,
                  show_side_panel=False, show_top_panel=False, dark_mode=True, color_background="#07111d")
    metrics = ("win_pct", "pts_per_game", "mean_margin", "fg_pct", "fg3_pct",
               "reb_per_game", "ast_per_game", "tov_per_game")
    matrix = pd.DataFrame([{x: row[x] for x in metrics} for row in monthly], index=[x["month"] for x in monthly])
    matrix = (matrix - matrix.mean()) / matrix.std(ddof=0).replace(0, 1)
    d3.matrix(matrix.fillna(0), title="Monthly Fingerprint", filepath=str(destination / "monthly-fingerprint.html"),
              showfig=False, cmap="interpolateRdBu", figsize=[1000, 600])
    tips = np.array([html.escape(f"{x['game_date']} · {x['opponent_abbrev']} · {x['venue_side']} · "
                                 f"NYK {x['pts']}–{x['opponent_pts']} · {x['wl']}") for x in games])
    d3.scatter(np.array([x["fg3a"] for x in games]), np.array([x["fg3_pct"] for x in games]),
               size=np.array([max(x["reb"], 1) for x in games]), color=np.array([x["wl"] for x in games]),
               tooltip=tips, title="Game Profiles", filepath=str(destination / "game-profiles.html"),
               showfig=False, show_side_panel=False, show_top_panel=False, dark_mode=True,
               color_background="#07111d", scale=True)
    d3.sankey(pd.DataFrame(paths), title="Result Paths", filepath=str(destination / "result-paths.html"),
              showfig=False, show_side_panel=False, show_top_panel=False, dark_mode=True,
              color_background="#07111d", figsize=[1000, 650])
    chord, grid, totals = build_opponent_views(games)
    d3.chord(pd.DataFrame(chord), title="Opponent Map",
             filepath=str(destination / "opponent-map.html"), showfig=False,
             show_side_panel=False, show_top_panel=False, dark_mode=True,
             color_background="#07111d", figsize=[900, 900])
    d3.violin(np.array([x["venue_side"].title() for x in games]),
              np.array([x["point_margin"] for x in games]),
              tooltip=np.array([html.escape(f"{x['game_date']} · {x['opponent_abbrev']} · "
                                                f"margin {x['point_margin']:+d}") for x in games]),
              x_order=["Home", "Away"], title="Margin Shape",
              filepath=str(destination / "margin-shape.html"), showfig=False,
              show_side_panel=False, show_top_panel=False, dark_mode=True,
              color_background="#07111d", figsize=[900, 650])
    d3.treemap(pd.DataFrame(totals), title="Opponent Share",
               filepath=str(destination / "opponent-share.html"), showfig=False,
               show_side_panel=False, show_top_panel=False, dark_mode=True,
               color_background="#07111d", figsize=[1000, 650])
    matchup = pd.DataFrame(
        [[row["home"], row["away"], row["overall"]] for row in grid],
        index=[row["opponent"] for row in grid], columns=["Home", "Away", "Overall"]) * 100
    d3.matrix(matchup.fillna(0), title="Matchup Grid", vmin=0, vmax=100,
              cmap="interpolateRdBu", filepath=str(destination / "matchup-grid.html"),
              showfig=False, figsize=[850, 700])
    _normalize_javascript_assets(destination)


def _generate_passing_chapter(passing_path, charts, previews):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from d3blocks import D3Blocks
    from knicks_history.passing import (aggregate_assist_edges, aggregate_passing_edges,
                                        load_assist_edges, load_passing_edges,
                                        load_research_edges)
    passing_path = Path(passing_path)
    header = passing_path.read_text(encoding="utf-8").splitlines()[0]
    assist_network = "assisted_makes" in header
    loader = load_assist_edges if assist_network else (
        load_research_edges if "retrieved_at" in header else load_passing_edges)
    rows = loader(passing_path)
    edges, seasons = (aggregate_assist_edges(rows) if assist_network
                      else aggregate_passing_edges(rows))
    title = "Five-season Assist Connections" if assist_network else "Five-season Passing Lanes"
    measure = "Assisted made baskets" if assist_network else "Passes"
    source_prefix = "Assister · " if assist_network else "Passer · "
    target_prefix = "Scorer · " if assist_network else "Receiver · "
    d3 = D3Blocks(support=False, verbose="error")
    d3.sankey(pd.DataFrame(edges), title=title,
              filepath=str(Path(charts) / "passing-lanes.html"), showfig=False,
              show_side_panel=False, show_top_panel=False, dark_mode=True,
              color_background="#05050a", figsize=[1200, 760])
    _normalize_javascript_assets(charts)
    plt.style.use("dark_background")
    top = edges[:12]
    fig, ax = plt.subplots(figsize=(12, 7), layout="constrained")
    ax.barh([f"{row['source'].replace(source_prefix, '')} → "
             f"{row['target'].replace(target_prefix, '')}" for row in reversed(top)],
            [row["weight"] for row in reversed(top)], color="#2378ff")
    ax.set(title=f"{title} · {seasons[0]} through {seasons[-1]}", xlabel=measure)
    fig.savefig(Path(previews) / "passing-lanes.png", dpi=150, facecolor="#05050a")
    plt.close(fig)
    return {"seasons": seasons, "rows": len(rows), "edges": len(edges),
            "relation_type": "assisted_made_basket" if assist_network else "passes_made",
            "measure_label": measure,
            "synthetic": all(row["synthetic"] for row in rows)}


def _generate_playoff_chapter(games, charts, previews):
    """Render the championship run as a responsive interactive timeline and PNG."""
    import matplotlib.pyplot as plt
    journey = build_playoff_journey(games)
    payload = json.dumps(journey, separators=(",", ":"), allow_nan=False)
    document = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>2026 championship road</title>
<style>
:root{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#05050a;color:#f8f9ff;--blue:#2378ff;--cyan:#5ce8ff;--orange:#ff7a18;--pink:#f24cff;--green:#62f6b1}
*{box-sizing:border-box}body{margin:0;padding:clamp(1rem,3vw,2.3rem);background:radial-gradient(circle at 90% 0,#2378ff26,transparent 35%),#05050a}.top{display:flex;justify-content:space-between;gap:1rem;align-items:end}.kicker{margin:0;color:#9ba4c8;font-size:.68rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1{margin:.35rem 0 0;font-size:clamp(2rem,6vw,4.8rem);line-height:.9;letter-spacing:-.06em}.record{color:var(--orange);font:800 clamp(2rem,5vw,4rem)/1 ui-monospace,monospace}.filters{display:flex;gap:.5rem;margin:1.5rem 0;overflow:auto}.filters button{min-height:42px;padding:.65rem .9rem;border:1px solid #8693c344;border-radius:999px;background:#0d0f1b;color:#e9ecff;cursor:pointer}.filters button[aria-pressed=true]{background:var(--orange);color:#05050a;border-color:var(--orange)}.series{display:grid;grid-template-columns:repeat(4,1fr);gap:.65rem}.series article,.game{border:1px solid #8d9fff26;border-radius:16px;background:linear-gradient(145deg,#121522,#090a12);padding:1rem}.series span{color:#8f98ba;font-size:.65rem;text-transform:uppercase;letter-spacing:.1em}.series strong{display:block;margin:.35rem 0;font-size:1.15rem}.series b{color:var(--green)}.timeline{display:grid;grid-template-columns:repeat(5,minmax(140px,1fr));gap:.65rem;margin-top:.65rem}.game{position:relative;overflow:hidden;min-height:154px;transition:.2s transform,.2s border-color}.game:hover,.game:focus-within{transform:translateY(-3px);border-color:#5ce8ff88}.game::before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--green)}.game.loss::before{background:var(--pink)}.game small{color:#8992b4}.game h2{margin:.55rem 0 .2rem;font-size:1.2rem}.score{font:750 1.55rem/1 ui-monospace,monospace}.margin{margin-top:.75rem;color:var(--green);font-size:.78rem}.loss .margin{color:#ff91d8}.milestone{margin-top:.7rem;padding:1rem;border:1px solid #ff7a1855;border-radius:16px;background:#28140c88;color:#ffd6b9}.milestone strong{color:var(--orange)}@media(max-width:760px){.top{align-items:start;flex-direction:column}.series{grid-template-columns:repeat(2,1fr)}.timeline{display:flex;overflow:auto;scroll-snap-type:x mandatory}.game{min-width:78vw;scroll-snap-align:start}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style></head><body><div class="top"><div><p class="kicker">NYK World / 2026 postseason</p><h1>Sixteen wins.<br>Fifty-three years.</h1></div><div class="record">16–3</div></div><div id="filters" class="filters" aria-label="Filter by playoff round"></div><div id="series" class="series"></div><div id="timeline" class="timeline" aria-live="polite"></div><div class="milestone"><strong>The Hand of OG.</strong> Game 4 of the Finals: New York erased a 29-point deficit before OG Anunoby's winning tip-in.</div><script>const journey=__PAYLOAD__;const filters=document.querySelector('#filters'),series=document.querySelector('#series'),timeline=document.querySelector('#timeline');const options=['All',...journey.series.map(x=>x.round)];function draw(selected='All'){timeline.replaceChildren();journey.games.filter(x=>selected==='All'||x.round===selected).forEach(x=>{const card=document.createElement('article');card.className='game '+(x.result==='W'?'win':'loss');const where=x.venue==='home'?'vs.':'@';card.innerHTML=`<small>Game ${x.game} · ${x.round}</small><h2>${where} ${x.opponent}</h2><div class="score">${x.points}–${x.opponent_points}</div><div class="margin">${x.result} · ${x.margin>0?'+':''}${x.margin} · Run margin ${x.cumulative_margin>0?'+':''}${x.cumulative_margin}</div>`;timeline.append(card)})}options.forEach((label,index)=>{const button=document.createElement('button');button.textContent=label;button.setAttribute('aria-pressed',String(index===0));button.onclick=()=>{[...filters.children].forEach(x=>x.setAttribute('aria-pressed','false'));button.setAttribute('aria-pressed','true');draw(label)};filters.append(button)});journey.series.forEach(x=>{const card=document.createElement('article');card.innerHTML=`<span>${x.round}</span><strong>${x.opponent_name}</strong><b>${x.wins}–${x.losses}</b>`;series.append(card)});draw();</script></body></html>"""
    Path(charts).mkdir(parents=True, exist_ok=True)
    (Path(charts) / "playoff-journey.html").write_text(
        document.replace("__PAYLOAD__", payload), encoding="utf-8")

    plt.style.use("dark_background")
    rows = journey["games"]
    fig, ax = plt.subplots(figsize=(14, 7), layout="constrained")
    colors = ["#62f6b1" if row["result"] == "W" else "#f24cff" for row in rows]
    ax.bar([row["game"] for row in rows], [row["margin"] for row in rows],
           color=colors, alpha=.82, label="Game margin")
    ax.plot([row["game"] for row in rows], [row["cumulative_margin"] for row in rows],
            color="#ff7a18", linewidth=2.5, marker="o", label="Cumulative margin")
    for item in journey["series"]:
        ax.axvline(item["end_game"] + .5, color="#ffffff33", linewidth=1)
        midpoint = (item["start_game"] + item["end_game"]) / 2
        ax.text(midpoint, 292, item["opponent"], ha="center", color="#aeb7d7",
                fontsize=10, fontweight="bold")
    ax.axhline(0, color="#ffffff55", linewidth=1)
    ax.set(title="Road to 16 wins · 2026 NBA champions", xlabel="Playoff game",
           ylabel="Point margin", xticks=range(1, 20), ylim=(-60, 315))
    ax.legend(frameon=False, loc="upper left")
    Path(previews).mkdir(parents=True, exist_ok=True)
    fig.savefig(Path(previews) / "playoff-journey.png", dpi=150, facecolor="#05050a")
    plt.close(fig)
    return {key: journey[key] for key in ("series", "wins", "losses", "point_differential",
                                           "longest_win_streak", "milestone")}


def _generate_synthetic_playoff_placeholder(charts, previews):
    """Keep the public teaching build explicit when it has no postseason rows."""
    import matplotlib.pyplot as plt
    Path(charts).mkdir(parents=True, exist_ok=True)
    html_document = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic playoff placeholder</title><style>:root{color-scheme:dark;font-family:Inter,system-ui,sans-serif;background:#05050a;color:#f8f9ff}body{min-height:100vh;margin:0;display:grid;place-items:center;padding:2rem;background:radial-gradient(circle at 70% 20%,#2378ff33,transparent 40%),#05050a}.card{max-width:760px;padding:clamp(2rem,6vw,5rem);border:1px solid #5ce8ff44;border-radius:28px;background:#0d101ccc}p{color:#aeb6d2;line-height:1.7}.label{color:#ff7a18;font-size:.7rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1{font-size:clamp(2.5rem,8vw,6rem);line-height:.9;letter-spacing:-.06em;margin:.7rem 0}</style></head><body><article class="card"><div class="label">Synthetic demonstration</div><h1>No historical playoff claims.</h1><p>This public teaching build exercises the iframe and release contracts without publishing observed postseason rows. The authenticated research preview contains the verified championship journey.</p></article></body></html>"""
    (Path(charts) / "playoff-journey.html").write_text(html_document, encoding="utf-8")
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6), layout="constrained")
    ax.set_axis_off()
    ax.text(.5, .58, "SYNTHETIC DEMONSTRATION", ha="center", va="center",
            color="#ff7a18", fontsize=18, fontweight="bold", transform=ax.transAxes)
    ax.text(.5, .42, "No historical playoff rows", ha="center", va="center",
            color="#f8f9ff", fontsize=30, transform=ax.transAxes)
    Path(previews).mkdir(parents=True, exist_ok=True)
    fig.savefig(Path(previews) / "playoff-journey.png", dpi=150, facecolor="#05050a")
    plt.close(fig)
    return {"available": False, "synthetic": True, "wins": 0, "losses": 0,
            "point_differential": 0, "series": []}


def _generate_model_chapter(games, features, model_dir, charts, previews):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from d3blocks import D3Blocks
    model_dir = Path(model_dir) if model_dir else None
    metrics, run_id = None, "ILLUSTRATIVE-SYNTHETIC-SIGNAL"
    if model_dir and (model_dir / "predictions.parquet").is_file():
        import polars as pl
        predictions = pl.read_parquet(model_dir / "predictions.parquet").sort("game_date").to_dicts()
        metrics = json.loads((model_dir / "metrics.json").read_text(encoding="utf-8"))
        run_id = json.loads((model_dir / "model-run.json").read_text(encoding="utf-8"))["run_id"]
    else:
        predictions = []
        for game, feature in zip(games, features):
            margin = feature.get("prior_5_point_margin") or 0
            probability = max(.15, min(.85, .5 + margin / 40))
            predictions.append({"game_date": game["game_date"],
                                "predicted_win_probability": probability,
                                "actual_win": 1 if game["wl"] == "W" else 0,
                                "predicted_margin": margin,
                                "actual_margin": game["point_margin"]})
    frame = pd.DataFrame({"date": [row["game_date"] for row in predictions],
                          "Win probability": [row["predicted_win_probability"] for row in predictions],
                          "Actual result": [row["actual_win"] for row in predictions]})
    d3 = D3Blocks(support=False, verbose="error")
    d3.timeseries(frame, datetime="date", dt_format="%Y-%m-%d", title="Model Signal",
                  filepath=str(Path(charts) / "model-signal.html"), showfig=False,
                  show_side_panel=False, show_top_panel=False, dark_mode=True,
                  color_background="#05050a")
    _normalize_javascript_assets(charts)
    plt.style.use("dark_background")
    fig, ax = plt.subplots(figsize=(12, 6), layout="constrained")
    ax.plot([row["game_date"] for row in predictions],
            [row["predicted_win_probability"] for row in predictions], color="#f24cff",
            marker="o", label="Pregame win probability")
    ax.scatter([row["game_date"] for row in predictions], [row["actual_win"] for row in predictions],
               color="#5ce8ff", label="Actual result", zorder=3)
    ax.set_ylim(-.05, 1.05); ax.set(title="Backtested model signal", ylabel="Probability / outcome")
    ax.tick_params(axis="x", rotation=45); ax.legend(frameon=False)
    fig.savefig(Path(previews) / "model-signal.png", dpi=150, facecolor="#05050a")
    plt.close(fig)
    return {"run_id": run_id, "metrics": metrics, "rows": len(predictions),
            "illustrative": model_dir is None}


def _write_story_manifest(space, season, revision, playoffs, passing, model, synthetic):
    chapters = [
        {"id": "opening", "label": "Opening signal"},
        {"id": "playoffs", "label": "Road to the title", "chart": "charts/playoff-journey.html",
         "preview": "previews/playoff-journey.png"},
        {"id": "season", "label": "Season arc"},
        {"id": "opponents", "label": "Opponent gravity"},
        {"id": "passing", "label": "Teammate network", "chart": "charts/passing-lanes.html",
         "preview": "previews/passing-lanes.png"},
        {"id": "models", "label": "Model lab", "chart": "charts/model-signal.html",
         "preview": "previews/model-signal.png"},
        {"id": "methods", "label": "Methods and provenance"},
    ]
    _write_json(Path(space) / "story-manifest.json",
                {"format_version": 1, "season": season, "dataset_revision": revision,
                 "synthetic": synthetic, "chapters": chapters, "playoffs": playoffs,
                 "passing": passing,
                 "model": model, "disclosures": ["backtest only", "not causal",
                                                   "not betting advice"]})


def _space_index(template, season, revision, games, playoffs=None,
                 mode_label="Historical extract", dataset_id=None):
    wins = sum(x["wl"] == "W" for x in games)
    playoffs = playoffs or {"available": False, "wins": 0, "losses": 0,
                            "point_differential": 0}
    playoff_available = playoffs.get("available", True)
    values = {"{{SEASON}}": season, "{{DATASET_REVISION}}": revision,
              "{{MODE_LABEL}}": mode_label, "{{CHART_COUNT}}": str(len(CHARTS)),
              "{{GAME_COUNT}}": str(len(games)), "{{WINS}}": str(wins),
              "{{LOSSES}}": str(len(games) - wins),
              "{{PLAYOFF_WINS}}": str(playoffs["wins"]),
              "{{PLAYOFF_LOSSES}}": str(playoffs["losses"]),
              "{{PLAYOFF_MARGIN}}": f'{playoffs["point_differential"]:+d}',
              "{{PLAYOFF_RECORD}}": (f'{playoffs["wins"]}–{playoffs["losses"]}'
                                      if playoff_available else "Synthetic only"),
              "{{PLAYOFF_HEADLINE}}": ("Sixteen wins. Fifty-three years."
                                        if playoff_available else "No historical playoff claims."),
              "{{PLAYOFF_COPY}}": ("Follow every series, every score, and the momentum swing that ended a 53-year championship wait."
                                    if playoff_available else "The public teaching build contains no observed postseason rows; the authenticated research release carries the verified title run."),
              "{{CHART_TABS}}": "\n".join(
                  f'<button id="tab-{chart["slug"]}" role="tab" tabindex="{0 if index == 0 else -1}" '
                  f'aria-selected="{str(index == 0).lower()}" aria-controls="chart-panel" '
                  f'data-chart="{chart["slug"]}" data-description="{html.escape(chart["description"], quote=True)}">'
                  f'{html.escape(chart["label"])}</button>' for index, chart in enumerate(CHARTS)),
              "{{PREVIEW_CARDS}}": "\n".join(
                  f'<figure><img src="previews/{chart["slug"]}.png" alt="{html.escape(chart["alt"], quote=True)}" />'
                  f'<figcaption>{html.escape(chart["label"])}</figcaption></figure>' for chart in CHARTS),
              "{{DATASET_LINK}}": (
                  f'<a href="https://huggingface.co/datasets/{dataset_id}/tree/{revision}" '
                  f'target="_blank" rel="noreferrer">Synthetic dataset and provenance</a>'
                  if dataset_id else '<a href="release-manifest.json">Build manifest</a>')}
    raw = {"{{CHART_TABS}}", "{{PREVIEW_CARDS}}", "{{DATASET_LINK}}"}
    for key, value in values.items():
        template = template.replace(key, value if key in raw else html.escape(value, quote=True))
    return template


def _data_contract(table_paths):
    import polars as pl
    keys = {"games": ["season", "season_type", "game_id", "team_id"],
            "pregame_features": ["season", "game_id"], "monthly_summary": ["season", "month"],
            "teams": ["season", "team_id"],
            "playoff_games": ["season", "season_type", "game_id", "team_id"]}
    tables = {}
    for name, paths in table_paths.items():
        frame = pl.concat([pl.read_parquet(path) for path in paths], how="diagonal_relaxed")
        tables[name] = {"keys": keys[name], "rows": frame.height,
                        "columns": [{"name": col, "type": str(frame.schema[col]),
                                     "nullable": frame[col].null_count() > 0} for col in frame.columns]}
    return {"version": 1, "feature_timing": {"history": "five completed games before target",
                                               "targets": ["target_win", "target_point_margin"]},
            "tables": tables}


def _write_payload_manifest(payload, metadata):
    payload = Path(payload)
    files = {path.relative_to(payload).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
             for path in sorted(payload.rglob("*")) if path.is_file() and path.name != MANIFEST_NAME}
    manifest = {**metadata, "files": files}; _write_json(payload / MANIFEST_NAME, manifest)
    return manifest


def build_hub_release(root, seasons, output, teams_dir, gate_path, space_source,
                      dataset_revision="LOCAL_PREVIEW", space_season=None,
                      allow_dirty=False, repo=None, passing_path=None, model_dir=None):
    require_visualization_python()
    seasons = [seasons] if isinstance(seasons, str) else list(dict.fromkeys(seasons))
    if not seasons: raise ValueError("Select at least one season")
    space_season = space_season or seasons[-1]
    if space_season not in seasons: raise ValueError("Space season must be included")
    output = Path(output)
    if output.exists(): raise FileExistsError("Use an empty output directory")
    release, source, selected = load_current_release(root, seasons)
    builder = repository_state(repo)
    source_dirty = source.get("git_dirty") is not False
    commits_match = source.get("git_sha") == builder["git_sha"]
    if not allow_dirty and (source_dirty or builder["git_dirty"] or not commits_match):
        raise ValueError("Publication builds require matching clean source and builder commits")
    gate = load_publication_gate(gate_path)
    status = publication_status(gate["complete"], source_dirty, dataset_revision,
                                builder["git_dirty"], commits_match,
                                force_preview=allow_dirty)
    if not public_payload_allowed(gate, synthetic=False):
        status = {"dataset_publishable": False, "space_publishable": False,
                  "publishable": False}
    dataset, space = output / "dataset", output / "space"; dataset.mkdir(parents=True)
    paths = {name: [] for name in ("games", "pregame_features", "monthly_summary", "teams",
                                   "playoff_games")}
    prepared, total = {}, 0
    for season in seasons:
        teams_path = resolve_team_dimension(teams_dir, season)
        teams = load_team_dimension(teams_path)
        games = enrich_games(selected[season]["rows"], teams)
        features, monthly = build_pregame_features(games), build_monthly_summary(games)
        team_rows = [dict(row, season=season) for row in teams.values()]
        values = {"games": games, "pregame_features": features,
                  "monthly_summary": monthly, "teams": team_rows}
        for name, rows in values.items():
            path = dataset / "data" / name / f"{season}.parquet"; _write_parquet(path, rows); paths[name].append(path)
        meta = dataset / "metadata" / "seasons" / season
        _write_json(meta / "coverage.json", selected[season]["coverage"])
        _write_json(meta / "source-manifest.json", source); shutil.copy2(teams_path, meta / "team-dimension.csv")
        prepared[season] = (games, features, monthly); total += len(games)
    playoff_rows, playoff_coverage = load_playoff_partition(release, space_season)
    playoff_teams_path = resolve_team_dimension(teams_dir, space_season)
    playoff_games = enrich_games(playoff_rows, load_team_dimension(playoff_teams_path))
    playoff_path = dataset / "data" / "playoff_games" / f"{space_season}.parquet"
    _write_parquet(playoff_path, playoff_games); paths["playoff_games"].append(playoff_path)
    playoff_meta = dataset / "metadata" / "seasons" / space_season
    _write_json(playoff_meta / "playoff-coverage.json", playoff_coverage)
    _write_json(dataset / "metadata/data-contract.json", _data_contract(paths))
    (dataset / "README.md").write_text(_dataset_readme(seasons, total, gate["dataset_license"]), encoding="utf-8")
    common = {"format_version": 1, "built_at": source.get("built_at"),
              "synthetic": False, "usage_scope": "local_research_only",
              "seasons": seasons, "rows": total, "postseason_rows": len(playoff_games),
              "source_release_id": source["release_id"],
              "source_git_sha": source.get("git_sha"), "source_git_dirty": source.get("git_dirty"),
              "builder_git_sha": builder["git_sha"], "builder_git_dirty": builder["git_dirty"],
              "source_builder_commits_match": commits_match,
              "redistribution_reviewed": gate["complete"]}
    dataset_status = {"dataset_publishable": status["dataset_publishable"],
                      "space_publishable": False, "publishable": False}
    dataset_manifest = _write_payload_manifest(
        dataset, {**common, **dataset_status, "payload": "dataset"})
    dataset_sha = digest(dataset / MANIFEST_NAME)
    space.mkdir(); template = _copy_space_source(space_source, space)
    games, features, monthly = prepared[space_season]
    (space / "README.md").write_text(_space_readme(space_season, dataset_revision), encoding="utf-8")
    _generate_d3(games, features, monthly, build_result_paths(games), space / "charts")
    _generate_previews(games, features, monthly, space / "previews")
    playoffs = _generate_playoff_chapter(playoff_games, space / "charts", space / "previews")
    if passing_path is None:
        raise ValueError("A passing CSV is required for a real research release")
    passing = _generate_passing_chapter(passing_path, space / "charts", space / "previews")
    model = _generate_model_chapter(games, features, model_dir, space / "charts", space / "previews")
    _write_story_manifest(space, space_season, dataset_revision, playoffs, passing, model, False)
    (space / "index.html").write_text(
        _space_index(template, space_season, dataset_revision, games, playoffs), encoding="utf-8")
    space_manifest = _write_payload_manifest(space, {**common, **status, "payload": "space", "space_season": space_season,
        "dataset_id": DATASET_ID, "dataset_revision": dataset_revision, "dataset_manifest_sha256": dataset_sha,
        "visualization": {"d3blocks": "2.3.4", "matplotlib": "3.11.2", "pandas": "2.3.3"}})
    summary = {"dataset": dataset_manifest, "space": space_manifest}; _write_json(output / "release.json", summary)
    return summary


def _validate_payload(payload, required):
    payload = Path(payload); manifest = json.loads((payload / MANIFEST_NAME).read_text(encoding="utf-8"))
    expected = set(manifest["files"])
    actual = {p.relative_to(payload).as_posix() for p in payload.rglob("*") if p.is_file() and p.name != MANIFEST_NAME}
    errors = [f"missing file: {x}" for x in sorted(expected - actual)]
    errors += [f"unexpected file: {x}" for x in sorted(actual - expected)]
    errors += [f"checksum mismatch: {x}" for x in sorted(expected & actual)
               if digest(payload / x) != manifest["files"][x]["sha256"]]
    errors += [f"missing required artifact: {x}" for x in required if x not in actual]
    for path in payload.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            content = path.read_text(encoding="utf-8", errors="replace").lower()
            errors += [f"forbidden marker {marker!r}: {path.relative_to(payload)}"
                       for marker in FORBIDDEN_MARKERS if marker in content]
            errors += [f"forbidden secret pattern: {path.relative_to(payload)}"
                       for pattern in FORBIDDEN_PATTERNS if pattern.search(content)]
    return manifest, errors


def validate_hub_release(output):
    output = Path(output)
    dataset, errors = _validate_payload(output / "dataset", ("README.md", "metadata/data-contract.json"))
    chart_artifacts = tuple(
        f"{folder}/{chart['slug']}.{suffix}"
        for chart in CHARTS for folder, suffix in (("charts", "html"), ("previews", "png")))
    story_artifacts = ("story-manifest.json", "charts/playoff-journey.html",
                       "previews/playoff-journey.png", "charts/passing-lanes.html",
                       "previews/passing-lanes.png", "charts/model-signal.html",
                       "previews/model-signal.png")
    space, space_errors = _validate_payload(
        output / "space", ("README.md", "index.html", *chart_artifacts, *story_artifacts))
    errors += space_errors
    if space.get("dataset_manifest_sha256") != digest(output / "dataset" / MANIFEST_NAME):
        errors.append("Space does not bind the current dataset manifest")
    if space["dataset_revision"] not in (output / "space/index.html").read_text(encoding="utf-8"):
        errors.append("Space index does not link its dataset revision")
    try:
        import polars as pl
        table_names = ["games", "pregame_features", "monthly_summary", "teams"]
        if not dataset.get("synthetic"):
            table_names.append("playoff_games")
        frames = {name: pl.concat([pl.read_parquet(x) for x in sorted((output / f"dataset/data/{name}").glob("*.parquet"))],
                                  how="diagonal_relaxed")
                  for name in table_names}
        games = frames["games"]
        if games.select(["season", "season_type", "game_id", "team_id"]).n_unique() != games.height:
            errors.append("games primary key is not unique")
        if games.schema["game_id"] != pl.String: errors.append("game_id is not text")
        if games.height != dataset["rows"]: errors.append("dataset manifest row count differs")
        if not dataset.get("synthetic"):
            playoff_games = frames["playoff_games"]
            if playoff_games.height != dataset.get("postseason_rows"):
                errors.append("dataset manifest postseason row count differs")
            if playoff_games.select(["season", "season_type", "game_id", "team_id"]).n_unique() != playoff_games.height:
                errors.append("playoff games primary key is not unique")
        for season in dataset["seasons"]:
            coverage = json.loads((output / f"dataset/metadata/seasons/{season}/coverage.json").read_text())
            observed = games.filter(pl.col("season") == season).height
            if observed != int(coverage["expected_games"]):
                errors.append(f"coverage count differs for {season}")
        features = frames["pregame_features"]
        if features.select(["season", "game_id"]).n_unique() != features.height:
            errors.append("pregame feature key is not unique")
        if features["history_games"].max() > 5: errors.append("pregame history exceeds five games")
        contract = json.loads((output / "dataset/metadata/data-contract.json").read_text())
        for name, frame in frames.items():
            columns = contract["tables"][name]["columns"]
            expected_schema = {column["name"]: column["type"] for column in columns}
            actual_schema = {column: str(dtype) for column, dtype in frame.schema.items()}
            if expected_schema != actual_schema:
                errors.append(f"data contract differs for {name}")
    except (ImportError, OSError, KeyError, ValueError) as exc:
        errors.append(f"Parquet contract validation failed: {exc}")
    if errors: raise ValueError("Hub release validation failed:\n- " + "\n- ".join(errors))
    return {"dataset": dataset, "space": space}
