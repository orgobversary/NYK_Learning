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
                     "google-analytics", "googletagmanager", "sk-")
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
        rows = [row for row in all_rows if row["season"] == season]
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

Original code is MIT licensed. `license: {license_name}` records that the code license
does not grant rights to third-party basketball facts. Do not upload this payload. It
contains no player or tracking data, causal claims, predictive model, or official
league artwork.
'''


def _synthetic_dataset_readme(season, rows):
    return f'''---
license: mit
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
basketball analysis. Source code and this invented fixture are MIT licensed.
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
license: mit
{dataset_metadata}short_description: Interactive {season} Knicks team-game visualizations
disable_embedding: false
---

# NYK World

Eight D3Blocks views and Matplotlib fallbacks for the {season} Knicks season. Snapshot
identifier: `{revision}`. Real-data builds are local research artifacts and must not be
uploaded.{dataset_note} The app has no player data or predictive model.
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


def _space_index(template, season, revision, games, mode_label="Historical extract",
                 dataset_id=None):
    wins = sum(x["wl"] == "W" for x in games)
    values = {"{{SEASON}}": season, "{{DATASET_REVISION}}": revision,
              "{{MODE_LABEL}}": mode_label, "{{CHART_COUNT}}": str(len(CHARTS)),
              "{{GAME_COUNT}}": str(len(games)), "{{WINS}}": str(wins),
              "{{LOSSES}}": str(len(games) - wins),
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
            "teams": ["season", "team_id"]}
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
                      allow_dirty=False, repo=None):
    require_visualization_python()
    seasons = [seasons] if isinstance(seasons, str) else list(dict.fromkeys(seasons))
    if not seasons: raise ValueError("Select at least one season")
    space_season = space_season or seasons[-1]
    if space_season not in seasons: raise ValueError("Space season must be included")
    output = Path(output)
    if output.exists(): raise FileExistsError("Use an empty output directory")
    _, source, selected = load_current_release(root, seasons)
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
    paths = {name: [] for name in ("games", "pregame_features", "monthly_summary", "teams")}
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
    _write_json(dataset / "metadata/data-contract.json", _data_contract(paths))
    (dataset / "README.md").write_text(_dataset_readme(seasons, total, gate["dataset_license"]), encoding="utf-8")
    common = {"format_version": 1, "built_at": source.get("built_at"),
              "synthetic": False, "usage_scope": "local_research_only",
              "seasons": seasons, "rows": total, "source_release_id": source["release_id"],
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
    (space / "index.html").write_text(_space_index(template, space_season, dataset_revision, games), encoding="utf-8")
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
    return manifest, errors


def validate_hub_release(output):
    output = Path(output)
    dataset, errors = _validate_payload(output / "dataset", ("README.md", "metadata/data-contract.json"))
    chart_artifacts = tuple(
        f"{folder}/{chart['slug']}.{suffix}"
        for chart in CHARTS for folder, suffix in (("charts", "html"), ("previews", "png")))
    space, space_errors = _validate_payload(
        output / "space", ("README.md", "index.html", *chart_artifacts))
    errors += space_errors
    if space.get("dataset_manifest_sha256") != digest(output / "dataset" / MANIFEST_NAME):
        errors.append("Space does not bind the current dataset manifest")
    if space["dataset_revision"] not in (output / "space/index.html").read_text(encoding="utf-8"):
        errors.append("Space index does not link its dataset revision")
    try:
        import polars as pl
        frames = {name: pl.concat([pl.read_parquet(x) for x in sorted((output / f"dataset/data/{name}").glob("*.parquet"))],
                                  how="diagonal_relaxed")
                  for name in ("games", "pregame_features", "monthly_summary", "teams")}
        games = frames["games"]
        if games.select(["season", "season_type", "game_id", "team_id"]).n_unique() != games.height:
            errors.append("games primary key is not unique")
        if games.schema["game_id"] != pl.String: errors.append("game_id is not text")
        if games.height != dataset["rows"]: errors.append("dataset manifest row count differs")
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
