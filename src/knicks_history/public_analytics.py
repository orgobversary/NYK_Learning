"""Public, source-specific NYK analytics built from BALLDONTLIE game records."""
from __future__ import annotations

import csv
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

PROVIDER = "balldontlie"
API_ROOT = "https://api.balldontlie.io/nba/v1"
TERMS_URL = "https://www.balldontlie.io/terms.html"
NYK_PROVIDER_TEAM_ID = 20
PUBLIC_GAME_FIELDS = (
    "game_key", "season", "season_type", "game_number", "game_date",
    "opponent", "opponent_abbrev", "venue_side", "nyk_score",
    "opponent_score", "result", "point_margin",
)
FEATURE_FIELDS = (
    "game_key", "season", "season_type", "game_number", "game_date",
    "opponent_abbrev", "venue_side", "days_rest", "games_played_before",
    "prior_5_points", "prior_5_opponent_points", "prior_5_margin",
    "prior_5_win_pct", "prior_10_points", "prior_10_opponent_points",
    "prior_10_margin", "prior_10_win_pct", "target_win",
    "target_point_margin",
)
PLAYOFF_SERIES_FIELDS = (
    "season", "series_number", "round", "opponent", "opponent_abbrev",
    "games", "wins", "losses", "point_margin", "first_game_number",
    "last_game_number",
)

DATASET_CARD = """---
license: other
task_categories:
- tabular-classification
- tabular-regression
tags:
- basketball
- sports-analytics
- time-series
configs:
- config_name: games
  data_files: games.csv
- config_name: pregame_features
  data_files: pregame_features.csv
- config_name: season_summary
  data_files: season_summary.csv
- config_name: monthly_summary
  data_files: monthly_summary.csv
- config_name: opponent_summary
  data_files: opponent_summary.csv
- config_name: playoff_series
  data_files: playoff_series.csv
---

# NYK World Analytics

Versioned, chart-ready New York Knicks game results and derived team-level analytics for
an independent, unofficial research and portfolio project. Each checkpoint covers only
completed seasons and includes a checksum manifest and explicit coverage evidence.

## Data contract

- `games.csv` contains minimal game values and hashed public keys, not provider IDs.
- `pregame_features.csv` uses only observations available before each game; target columns
  are included for reproducible evaluation.
- Summary tables aggregate seasons, months, opponents, venues, and playoff series.
- `model_predictions.csv` and `model_metrics.json`, when present, come from expanding-window
  chronological tests and include simple baselines.

Raw API responses, provider identifiers, credentials, and player-level records are not
published. Read `release-manifest.json` before reuse: it records the source, season scope,
terms-review basis, checksums, and limitations for the exact checkpoint.

## Use and limitations

This dataset is best-effort historical research, not an official record, live feed, or
betting product. The models are descriptive portfolio demonstrations and do not establish
causality. Original pipeline software is licensed under AGPL-3.0-or-later; original
documentation and visual design are licensed under CC BY-SA 4.0. Third-party facts remain
subject to the source terms linked from the manifest. This project is
not affiliated with or endorsed by the NBA or New York Knicks.
"""


def season_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _integer(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{name} must not be negative")
    return result


def _team(game, side):
    team = game.get(f"{side}_team")
    if not isinstance(team, dict):
        raise ValueError(f"Missing {side}_team")
    abbreviation = team.get("abbreviation")
    if not isinstance(abbreviation, str) or not abbreviation.strip():
        raise ValueError(f"Missing {side} team abbreviation")
    return team


def _game_date(value):
    if not isinstance(value, str):
        raise ValueError("Game date must be text")
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid game date: {value}") from exc


def normalize_games(payload, expected_season=None, expected_type=None):
    """Normalize a complete provider page set without exposing provider IDs."""
    games = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(games, list):
        raise ValueError("BALLDONTLIE response requires a data list")
    output, seen = [], set()
    for item in games:
        if not isinstance(item, dict):
            raise ValueError("Game entry must be an object")
        provider_id = str(item.get("id", ""))
        if not provider_id or provider_id in seen:
            raise ValueError("Missing or duplicate provider game ID")
        seen.add(provider_id)
        status = str(item.get("status", "")).strip().lower()
        state = str(item.get("status_state", "")).strip().lower()
        if status != "final" and state != "final":
            raise ValueError(f"Game {provider_id} is not final")
        home, visitor = _team(item, "home"), _team(item, "visitor")
        home_is_nyk = home["abbreviation"].upper() == "NYK"
        visitor_is_nyk = visitor["abbreviation"].upper() == "NYK"
        if home_is_nyk == visitor_is_nyk:
            raise ValueError(f"Game {provider_id} must contain NYK exactly once")
        start_year = _integer(item.get("season"), "season")
        season = season_label(start_year)
        raw_type = str(item.get("season_type", "")).strip().lower()
        postseason = bool(item.get("postseason"))
        season_type = "Playoffs" if postseason or raw_type == "playoffs" else "Regular Season"
        if raw_type in {"preseason", "playin"}:
            raise ValueError(f"Unsupported season type for public v1: {raw_type}")
        if raw_type == "ist" and str(item.get("ist_stage", "")).strip().lower() == "championship":
            raise ValueError("NBA Cup championship does not count toward the regular season")
        if expected_season and season != expected_season:
            raise ValueError(f"Expected {expected_season}, received {season}")
        if expected_type and season_type != expected_type:
            raise ValueError(f"Expected {expected_type}, received {season_type}")
        home_score = _integer(item.get("home_team_score"), "home_team_score")
        visitor_score = _integer(item.get("visitor_team_score"), "visitor_team_score")
        game_date = _game_date(item.get("date"))
        if home_is_nyk:
            opponent, venue = visitor, "home"
            nyk_score, opponent_score = home_score, visitor_score
        else:
            opponent, venue = home, "away"
            nyk_score, opponent_score = visitor_score, home_score
        if nyk_score == opponent_score:
            raise ValueError(f"Completed game {provider_id} cannot end tied")
        private_key = f"{PROVIDER}:{provider_id}"
        public_key = hashlib.sha256(
            f"{season}|{season_type}|{game_date}|{opponent['abbreviation']}|{venue}".encode()
        ).hexdigest()[:16]
        output.append({
            "source_game_key": private_key,
            "game_key": public_key,
            "season": season,
            "season_type": season_type,
            "game_date": game_date,
            "opponent": str(opponent.get("full_name") or opponent.get("name") or
                            opponent["abbreviation"]),
            "opponent_abbrev": opponent["abbreviation"].upper(),
            "venue_side": venue,
            "nyk_score": nyk_score,
            "opponent_score": opponent_score,
            "result": "W" if nyk_score > opponent_score else "L",
            "point_margin": nyk_score - opponent_score,
        })
    output.sort(key=lambda row: (row["season"], row["season_type"],
                                 row["game_date"], row["source_game_key"]))
    keys = [row["game_key"] for row in output]
    if len(keys) != len(set(keys)):
        raise ValueError("Public game keys are not unique")
    return output


def _request_page(request, req, delay, sleep, max_attempts):
    retryable = {408, 429, 500, 502, 503, 504}
    for attempt in range(max_attempts):
        try:
            with request(req, timeout=45) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in retryable or attempt + 1 == max_attempts:
                raise RuntimeError(
                    f"BALLDONTLIE request failed with HTTP {exc.code}"
                ) from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                wait = float(retry_after) if retry_after is not None else 0
            except ValueError:
                wait = 0
            sleep(max(wait, max(delay, 1.0) * (2 ** attempt)))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 == max_attempts:
                raise RuntimeError("BALLDONTLIE request failed") from exc
            sleep(max(delay, 1.0) * (2 ** attempt))
    raise RuntimeError("BALLDONTLIE request failed")


def fetch_partition(api_key, season, season_type, request=None, delay=12.5,
                    raw_directory=None, sleep=time.sleep, max_attempts=4):
    """Fetch one season partition through the provider's official API."""
    if not api_key:
        raise ValueError("BALLDONTLIE_API_KEY is required")
    start_year = int(season[:4])
    provider_types = ("playoffs",) if season_type == "Playoffs" else ("regular", "ist")
    request = request or urllib.request.urlopen
    pages, rows, excluded_cup_finals = [], [], 0
    for provider_type in provider_types:
        cursor, provider_page = None, 0
        while True:
            query = [("team_ids[]", str(NYK_PROVIDER_TEAM_ID)),
                     ("seasons[]", str(start_year)),
                     ("season_type", provider_type), ("per_page", "100")]
            if cursor is not None:
                query.append(("cursor", str(cursor)))
            url = f"{API_ROOT}/games?{urllib.parse.urlencode(query)}"
            req = urllib.request.Request(url, headers={"Authorization": api_key,
                                                       "User-Agent": "NYK-Learning/0.1"})
            try:
                raw = _request_page(request, req, delay, sleep, max_attempts)
            except RuntimeError as exc:
                raise RuntimeError(
                    f"BALLDONTLIE request failed for {season} {season_type} ({provider_type})"
                ) from exc
            payload = json.loads(raw)
            page_rows = payload.get("data")
            if not isinstance(page_rows, list):
                raise ValueError("Provider page is missing data")
            page_sha = hashlib.sha256(raw).hexdigest()
            provider_page += 1
            page_record = {"sha256": page_sha, "bytes": len(raw),
                           "provider_season_type": provider_type,
                           "page_number": provider_page}
            if raw_directory is not None:
                raw_directory = Path(raw_directory)
                raw_directory.mkdir(parents=True, exist_ok=True)
                raw_path = raw_directory / (
                    f"{season}-{provider_type}-{provider_page}-{page_sha[:12]}.json"
                )
                raw_path.write_bytes(raw)
                page_record["file"] = raw_path.name
            pages.append(page_record)
            for item in page_rows:
                cup_final = (provider_type == "ist" and
                             str(item.get("ist_stage", "")).strip().lower() == "championship")
                if cup_final:
                    excluded_cup_finals += 1
                else:
                    rows.append(item)
            meta = payload.get("meta") or {}
            next_cursor = meta.get("next_cursor")
            # Throttle every provider request, including the final page in a
            # partition, so sequential season partitions cannot burst the API.
            if delay:
                sleep(delay)
            if next_cursor is None:
                break
            if next_cursor == cursor:
                raise ValueError("Provider pagination cursor did not advance")
            cursor = next_cursor
    normalized = normalize_games({"data": rows}, season, season_type)
    return normalized, {"provider": PROVIDER, "endpoint": f"{API_ROOT}/games",
                        "season": season, "season_type": season_type,
                        "provider_season_types": list(provider_types),
                        "excluded_nba_cup_championship_games": excluded_cup_finals,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "pages": pages, "rows": len(normalized), "terms_url": TERMS_URL}


def number_games(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["season"], row["season_type"])].append(dict(row))
    output = []
    for _, values in sorted(grouped.items()):
        for number, row in enumerate(sorted(values, key=lambda x: (x["game_date"], x["game_key"])), 1):
            row["game_number"] = number
            output.append(row)
    return output


def public_games(rows):
    return [{field: row[field] for field in PUBLIC_GAME_FIELDS} for row in number_games(rows)]


def _window(values, field, size):
    subset = values[-size:]
    return round(sum(row[field] for row in subset) / len(subset), 6) if subset else None


def build_pregame_features(rows):
    features = []
    for (season, season_type), games in sorted(_group(number_games(rows), "season", "season_type").items()):
        history = []
        for game in sorted(games, key=lambda row: row["game_number"]):
            previous_date = date.fromisoformat(history[-1]["game_date"]) if history else None
            current_date = date.fromisoformat(game["game_date"])
            feature = {
                "game_key": game["game_key"], "season": season, "season_type": season_type,
                "game_number": game["game_number"], "game_date": game["game_date"],
                "opponent_abbrev": game["opponent_abbrev"], "venue_side": game["venue_side"],
                "days_rest": (current_date - previous_date).days - 1 if previous_date else None,
                "games_played_before": len(history),
            }
            for size in (5, 10):
                feature[f"prior_{size}_points"] = _window(history, "nyk_score", size)
                feature[f"prior_{size}_opponent_points"] = _window(history, "opponent_score", size)
                feature[f"prior_{size}_margin"] = _window(history, "point_margin", size)
                feature[f"prior_{size}_win_pct"] = _window(
                    [{**row, "win": int(row["result"] == "W")} for row in history], "win", size)
            feature["target_win"] = int(game["result"] == "W")
            feature["target_point_margin"] = game["point_margin"]
            features.append(feature)
            history.append(game)
    return features


def _group(rows, *keys):
    grouped = defaultdict(list)
    for row in rows:
        grouped[tuple(row[key] for key in keys)].append(row)
    return grouped


def build_season_summary(rows):
    output = []
    for (season, season_type), games in sorted(_group(number_games(rows), "season", "season_type").items()):
        wins = sum(game["result"] == "W" for game in games)
        margins = [game["point_margin"] for game in games]
        streak, longest_win, longest_loss = 0, 0, 0
        for game in sorted(games, key=lambda row: row["game_number"]):
            streak = streak + 1 if game["result"] == "W" and streak >= 0 else (
                streak - 1 if game["result"] == "L" and streak <= 0 else
                (1 if game["result"] == "W" else -1))
            longest_win, longest_loss = max(longest_win, streak), min(longest_loss, streak)
        output.append({"season": season, "season_type": season_type, "games": len(games),
                       "wins": wins, "losses": len(games) - wins,
                       "points_per_game": round(sum(x["nyk_score"] for x in games) / len(games), 6),
                       "opponent_points_per_game": round(sum(x["opponent_score"] for x in games) / len(games), 6),
                       "mean_margin": round(sum(margins) / len(margins), 6),
                       "home_games": sum(x["venue_side"] == "home" for x in games),
                       "away_games": sum(x["venue_side"] == "away" for x in games),
                       "longest_win_streak": longest_win,
                       "longest_loss_streak": abs(longest_loss)})
    return output


def build_monthly_summary(rows):
    output = []
    grouped = defaultdict(list)
    for row in number_games(rows):
        grouped[(row["season"], row["season_type"], row["game_date"][:7])].append(row)
    for (season, season_type, month), games in sorted(grouped.items()):
        wins = sum(game["result"] == "W" for game in games)
        output.append({"season": season, "season_type": season_type, "month": month,
                       "games": len(games), "wins": wins, "losses": len(games) - wins,
                       "win_pct": round(wins / len(games), 6),
                       "points_per_game": round(sum(x["nyk_score"] for x in games) / len(games), 6),
                       "opponent_points_per_game": round(sum(x["opponent_score"] for x in games) / len(games), 6),
                       "mean_margin": round(sum(x["point_margin"] for x in games) / len(games), 6)})
    return output


def build_opponent_summary(rows):
    output = []
    for (season, season_type, opponent, venue), games in sorted(
            _group(number_games(rows), "season", "season_type", "opponent_abbrev", "venue_side").items()):
        wins = sum(game["result"] == "W" for game in games)
        output.append({"season": season, "season_type": season_type,
                       "opponent_abbrev": opponent, "venue_side": venue,
                       "games": len(games), "wins": wins, "losses": len(games) - wins,
                       "points_for": sum(x["nyk_score"] for x in games),
                       "points_against": sum(x["opponent_score"] for x in games),
                       "point_margin": sum(x["point_margin"] for x in games)})
    return output


def build_playoff_series(rows):
    output = []
    grouped = _group([row for row in number_games(rows) if row["season_type"] == "Playoffs"], "season")
    for (season,), games in sorted(grouped.items()):
        blocks = []
        for game in sorted(games, key=lambda row: row["game_number"]):
            if not blocks or blocks[-1][0]["opponent_abbrev"] != game["opponent_abbrev"]:
                blocks.append([])
            blocks[-1].append(game)
        if len(blocks) > 4:
            raise ValueError(f"Too many playoff series for {season}: {len(blocks)}")
        opponents = [series[0]["opponent_abbrev"] for series in blocks]
        if len(opponents) != len(set(opponents)):
            raise ValueError(f"Repeated non-contiguous playoff opponent for {season}")
        labels = ["Round One", "Conference Semifinals", "Conference Finals", "NBA Finals"][:len(blocks)]
        for index, (label, series) in enumerate(zip(labels, blocks), 1):
            if not 4 <= len(series) <= 7:
                raise ValueError(
                    f"Invalid playoff series length for {season} {series[0]['opponent_abbrev']}: {len(series)}"
                )
            wins = sum(game["result"] == "W" for game in series)
            output.append({"season": season, "series_number": index, "round": label,
                           "opponent": series[0]["opponent"],
                           "opponent_abbrev": series[0]["opponent_abbrev"],
                           "games": len(series), "wins": wins, "losses": len(series) - wins,
                           "point_margin": sum(game["point_margin"] for game in series),
                           "first_game_number": series[0]["game_number"],
                           "last_game_number": series[-1]["game_number"]})
    return output


def _write_csv(path, rows, fields=None):
    rows = list(rows)
    if not rows and not fields:
        raise ValueError(f"Cannot infer fields for empty table {path.name}")
    fields = list(fields or rows[0])
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_public_release(rows, destination, source_manifests, terms_review, synthetic=False):
    """Write a closed, aggregate-oriented public dataset payload."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Use an empty public release directory")
    destination.mkdir(parents=True)
    tables = {
        "games.csv": (public_games(rows), PUBLIC_GAME_FIELDS),
        "pregame_features.csv": (build_pregame_features(rows), FEATURE_FIELDS),
        "season_summary.csv": (build_season_summary(rows), None),
        "monthly_summary.csv": (build_monthly_summary(rows), None),
        "opponent_summary.csv": (build_opponent_summary(rows), None),
        "playoff_series.csv": (build_playoff_series(rows), PLAYOFF_SERIES_FIELDS),
    }
    for filename, (values, fields) in tables.items():
        _write_csv(destination / filename, values, fields)
    (destination / "README.md").write_text(DATASET_CARD, encoding="utf-8")
    source_digest = hashlib.sha256(json.dumps(source_manifests, sort_keys=True).encode()).hexdigest()
    manifest = {
        "format_version": 1, "provider": PROVIDER, "synthetic": bool(synthetic),
        "public_payload": "minimal_game_values_and_derived_aggregates",
        "terms_url": TERMS_URL, "terms_review": terms_review,
        "source_manifest_sha256": source_digest,
        "seasons": sorted({row["season"] for row in rows}),
        "regular_season_games": sum(row["season_type"] == "Regular Season" for row in rows),
        "playoff_games": sum(row["season_type"] == "Playoffs" for row in rows),
        "limitations": ["unofficial independent project", "provider data is best effort",
                        "no player statistics in public v1", "not betting advice"],
    }
    manifest["files"] = {
        path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size}
        for path in sorted(destination.iterdir()) if path.is_file()
    }
    (destination / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
