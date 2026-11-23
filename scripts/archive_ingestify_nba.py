"""Sync configured NBA Stats datasets through Ingestify, then archive them for ETL."""
import argparse
import importlib.metadata
from pathlib import Path

from knicks_history.pipeline import archive


def main():
    parser = argparse.ArgumentParser(
        description="Sync the private NBA lake and copy accepted raw responses into the Knicks ETL"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/live"))
    args = parser.parse_args()

    from ingestify.main import get_engine

    engine = get_engine(str(args.config))
    datasets = engine.iter_datasets(
        auto_ingest=True,
        provider="nba_stats",
        dataset_type="league_game_log",
        dataset_state="complete",
    )
    count = 0
    for dataset in datasets:
        season = str(dataset.identifier["season"])
        season_type = str(dataset.identifier["season_type"])
        loaded = engine.store.load_files(dataset).get_file("league_game_log")
        if loaded is None:
            raise RuntimeError(f"Missing league_game_log file for {dataset.identifier}")
        raw = loaded.stream.read()
        source = {
            "endpoint": "LeagueGameLog",
            "nba_api_version": importlib.metadata.version("nba_api"),
            "ingestify_version": importlib.metadata.version("ingestify"),
            "ingestify_dataset_id": dataset.dataset_id,
            "LeagueID": "00",
            "PlayerOrTeam": "T",
            "Season": season,
            "SeasonType": season_type,
        }
        result = archive(args.root, raw, season, season_type, False, source)
        print(
            f"Archived {season} {season_type}: {result['row_count']} Knicks games",
            flush=True,
        )
        count += 1
    if not count:
        raise SystemExit("No complete NBA Stats datasets matched the configured plans")


if __name__ == "__main__":
    main()
