import argparse
import importlib.metadata
import json
from pathlib import Path
from .nba_client import fetch_league_game_log
from .pipeline import KINDS, archive, build, check_season


def fetch_raw(season, kind):
    return fetch_league_game_log(season, kind)


def main():
    parser = argparse.ArgumentParser(description='Reproducible Knicks team-game ETL')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('ingest', 'fetch'):
        p = commands.add_parser(name)
        p.add_argument('--season', required=True, type=check_season)
        p.add_argument('--season-type', choices=KINDS, default='Regular Season')
        p.add_argument('--root', type=Path, required=True)
        p.add_argument('--allow-empty', action='store_true')
        if name == 'ingest':
            p.add_argument('--input', type=Path, required=True)
            p.add_argument('--synthetic', action='store_true')
    p = commands.add_parser('build')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--expected', type=Path)
    p.add_argument('--parquet', action='store_true')
    args = parser.parse_args()
    if args.command == 'build':
        print(build(args.root, args.expected, args.parquet))
        return
    if args.command == 'fetch':
        print(f'Fetching {args.season} {args.season_type} from NBA Stats...', flush=True)
        raw = fetch_raw(args.season, args.season_type)
        source = {'endpoint': 'LeagueGameLog', 'nba_api_version': importlib.metadata.version('nba_api'),
                  'LeagueID': '00', 'PlayerOrTeam': 'T', 'Season': args.season, 'SeasonType': args.season_type}
        synthetic = False
    else:
        raw, source, synthetic = args.input.read_bytes(), {'input': str(args.input)}, args.synthetic
    result = archive(args.root, raw, args.season, args.season_type, synthetic, source, args.allow_empty)
    print(f"Archived {result['season']} {result['season_type']}: {result['row_count']} Knicks games", flush=True)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
