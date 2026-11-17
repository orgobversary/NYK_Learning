"""Fetch private, season-total Knicks passing research with cached raw responses."""
import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from knicks_history.passing import RESEARCH_FIELDS, normalize_passes_made, participant_ids

TEAM_ID = 1610612752
PLAYER_SOURCE = "https://stats.nba.com/stats/leaguedashplayerstats"
PASSING_SOURCE = "https://stats.nba.com/stats/playerdashptpass"


def request_json(factory, attempts=3):
    for attempt in range(attempts):
        try:
            return factory().get_json().encode("utf-8")
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError("NBA Stats request did not complete")


def cache_raw(root, season, label, raw):
    sha = hashlib.sha256(raw).hexdigest()
    path = root / "raw" / season / label / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(raw)
    return path


def fetch_season(season, root, rights_basis, delay=1.5):
    from nba_api.stats.endpoints.leaguedashplayerstats import LeagueDashPlayerStats
    from nba_api.stats.endpoints.playerdashptpass import PlayerDashPtPass

    participant_raw = request_json(lambda: LeagueDashPlayerStats(
        season=season, season_type_all_star="Regular Season", team_id_nullable=str(TEAM_ID),
        per_mode_detailed="Totals", timeout=45))
    cache_raw(root, season, "participants", participant_raw)
    participants = participant_ids(json.loads(participant_raw))
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for player_id in sorted(participants, key=int):
        raw = request_json(lambda player_id=player_id: PlayerDashPtPass(
            team_id=TEAM_ID, player_id=int(player_id), season=season,
            season_type_all_star="Regular Season", per_mode_simple="Totals", timeout=45))
        cache_raw(root, season, player_id, raw)
        rows.extend(normalize_passes_made(
            json.loads(raw), season, player_id, participants, PASSING_SOURCE,
            retrieved_at, rights_basis, raw))
        time.sleep(delay)
    output = root / "edges" / f"{season}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESEARCH_FIELDS)
        writer.writeheader(); writer.writerows(sorted(rows, key=lambda row: (
            row["passer_player_id"], row["receiver_player_id"])))
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", action="append", required=True)
    parser.add_argument("--root", type=Path, default=Path("data/research/player_passing"))
    parser.add_argument("--rights-basis", required=True,
                        help="documented private-research authorization; stored in every row")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    for season in args.season:
        print(fetch_season(season, args.root, args.rights_basis, args.delay))


if __name__ == "__main__":
    main()
