"""Build a private assist-to-scorer network from documented play-by-play Parquet."""
import argparse
import csv
import hashlib
import io
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from knicks_history.passing import ASSIST_FIELDS, normalize_assist_events

TEAM_ID = "1610612752"
BASE_URL = "https://basketball-data.billmill.org/nba/stats"


def download(url, attempts=3):
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "NYK-Learning private research"})
            with urlopen(request, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError("Download did not complete")


def cache_raw(root, season, label, content):
    digest = hashlib.sha256(content).hexdigest()
    path = root / "raw" / season / label / f"{digest}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    return digest


def load_team_games(root, season):
    current = (Path(root) / "CURRENT").read_text(encoding="utf-8").strip()
    path = Path(root) / "releases" / current / "team_games.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        return [row for row in csv.DictReader(stream)
                if row["season"] == season and row["season_type"] == "Regular Season"]


def fetch_season(season, root, team_root, rights_basis):
    import polars as pl
    ending_year = int(season[:4]) + 1
    events_url = f"{BASE_URL}/game_events/season={ending_year}/data.parquet"
    players_url = f"{BASE_URL}/player_seasons/season={ending_year}/data.parquet"
    event_content, player_content = download(events_url), download(players_url)
    event_digest = cache_raw(root, season, "game_events", event_content)
    player_digest = cache_raw(root, season, "player_seasons", player_content)
    combined_digest = hashlib.sha256(
        f"{event_digest}:{player_digest}".encode("ascii")).hexdigest()
    events = pl.read_parquet(io.BytesIO(event_content)).to_dicts()
    players = pl.read_parquet(io.BytesIO(player_content)).to_dicts()
    games = load_team_games(team_root, season)
    rows = normalize_assist_events(
        events, players, games, season, events_url,
        datetime.now(timezone.utc).isoformat(), rights_basis, combined_digest, TEAM_ID)
    output = Path(root) / "assist_edges" / f"{season}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=ASSIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output


def combine_edges(paths, output):
    rows = []
    for path in paths:
        with Path(path).open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != ASSIST_FIELDS:
                raise ValueError(f"Assist schema differs in {path}")
            rows.extend(reader)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=ASSIST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", action="append", required=True)
    parser.add_argument("--root", type=Path, default=Path("data/research/player_passing"))
    parser.add_argument("--team-root", type=Path, default=Path("data/live"))
    parser.add_argument("--rights-basis", required=True,
                        help="documented private-research basis stored in every row")
    args = parser.parse_args()
    outputs = [fetch_season(season, args.root, args.team_root, args.rights_basis)
               for season in args.season]
    for output in outputs:
        print(output)
    if len(outputs) > 1:
        print(combine_edges(outputs, args.root / "assist_edges" / "five-season.csv"))


if __name__ == "__main__":
    main()
