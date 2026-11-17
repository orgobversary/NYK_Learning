"""Train chronological private-research baselines from pregame feature Parquet."""
import argparse
import json
from pathlib import Path

from knicks_history.modeling import train_models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True,
                        help="Parquet file or directory of season Parquet files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        import polars as pl
    except ImportError as exc:
        raise SystemExit("Install the ml extra") from exc
    paths = sorted(args.features.glob("*.parquet")) if args.features.is_dir() else [args.features]
    if not paths:
        raise SystemExit("No feature Parquet files found")
    rows = pl.concat([pl.read_parquet(path) for path in paths], how="diagonal_relaxed").to_dicts()
    print(json.dumps(train_models(rows, args.output), indent=2))


if __name__ == "__main__":
    main()
