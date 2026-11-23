"""Build an immutable public-analytics checkpoint from BALLDONTLIE game data."""
import argparse
import csv
import hashlib
import json
import os
import shutil
import tomllib
from datetime import date
from pathlib import Path

from knicks_history.public_analytics import (
    build_pregame_features, fetch_partition, normalize_games, write_public_release,
)
from knicks_history.public_modeling import train_expanding_models


def load_fixture(path, season, season_type):
    raw = Path(path).read_bytes()
    return normalize_games(json.loads(raw), season, season_type), {
        "provider": "balldontlie", "fixture": True,
        "sha256": hashlib.sha256(raw).hexdigest(), "season": season,
        "season_type": season_type,
    }


def refresh_manifest(destination, model_report=None):
    path = Path(destination) / "release-manifest.json"
    manifest = json.loads(path.read_text())
    if model_report:
        manifest["model"] = {
            "evaluation": model_report["evaluation"],
            "first_test_season": model_report["first_test_season"],
            "last_test_season": model_report["last_test_season"],
        }
    manifest["files"] = {
        item.name: {"sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                    "bytes": item.stat().st_size}
        for item in sorted(Path(destination).iterdir())
        if item.is_file() and item.name != path.name
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_coverage(rows, source_manifests, path, start, end):
    with Path(path).open(newline="", encoding="utf-8") as stream:
        expected = list(csv.DictReader(stream))
    expected = [row for row in expected if start <= int(row["season"][:4]) <= end]
    expected_keys = {(row["season"], row["season_type"]) for row in expected}
    source_keys = {(row["season"], row["season_type"]) for row in source_manifests}
    if expected_keys != source_keys:
        raise ValueError(f"Coverage partitions differ: expected={sorted(expected_keys)} source={sorted(source_keys)}")
    evidence = []
    for item in expected:
        key = (item["season"], item["season_type"])
        observed = sum((row["season"], row["season_type"]) == key for row in rows)
        expected_games = int(item["expected_games"])
        if observed != expected_games:
            raise ValueError(f"Coverage mismatch for {key}: expected {expected_games}, observed {observed}")
        evidence.append({**item, "expected_games": expected_games, "observed_games": observed,
                         "status": "count_matches"})
    return evidence


def validate_live_policy(path, start, end, reviewed_at, basis):
    with Path(path).open("rb") as stream:
        policy = tomllib.load(stream)
    scope = policy["initial_scope"]
    expected_start = int(scope["first_season"][:4])
    expected_end = int(scope["last_season"][:4])
    if (start, end) != (expected_start, expected_end):
        raise ValueError(
            f"Requested scope {start}-{end} differs from approved policy "
            f"{expected_start}-{expected_end}"
        )
    if scope.get("include_current_incomplete_season") is not False:
        raise ValueError("Public v1 policy must exclude the current incomplete season")
    try:
        review_date = date.fromisoformat(reviewed_at)
    except ValueError as exc:
        raise ValueError("Terms review date must use YYYY-MM-DD") from exc
    if review_date > date.today():
        raise ValueError("Terms review date cannot be in the future")
    if not basis.strip():
        raise ValueError("Terms review basis must not be empty")
    return policy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=int, default=2017)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--terms-reviewed-at", required=True)
    parser.add_argument("--terms-basis", required=True)
    parser.add_argument("--fixture", type=Path,
                        help="offline test fixture; builds one regular-season partition")
    parser.add_argument("--no-models", action="store_true")
    parser.add_argument("--viewer-source", type=Path,
                        default=Path("huggingface/public-viewer"))
    parser.add_argument("--coverage", type=Path,
                        default=Path("config/public-expected.csv"))
    parser.add_argument("--policy", type=Path,
                        default=Path("config/public-analytics.toml"))
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use an empty output directory")
    rows, source_manifests = [], []
    if args.fixture:
        values, source = load_fixture(args.fixture, f"{args.start}-{(args.start + 1) % 100:02d}",
                                      "Regular Season")
        rows.extend(values); source_manifests.append(source)
    else:
        validate_live_policy(args.policy, args.start, args.end,
                             args.terms_reviewed_at, args.terms_basis)
        api_key = os.environ.get("BALLDONTLIE_API_KEY")
        if not api_key:
            raise SystemExit("BALLDONTLIE_API_KEY is not set")
        for year in range(args.start, args.end + 1):
            season = f"{year}-{(year + 1) % 100:02d}"
            for season_type in ("Regular Season", "Playoffs"):
                values, source = fetch_partition(
                    api_key, season, season_type,
                    raw_directory=args.output.parent / "private-source" / "raw")
                rows.extend(values); source_manifests.append(source)
    terms_review = {"reviewed_at": args.terms_reviewed_at, "basis": args.terms_basis,
                    "review_required_each_checkpoint": True}
    coverage = None
    if not args.fixture:
        coverage = validate_coverage(rows, source_manifests, args.coverage, args.start, args.end)
    manifest = write_public_release(rows, args.output, source_manifests, terms_review,
                                    synthetic=bool(args.fixture))
    if coverage is not None:
        (args.output / "coverage.json").write_text(
            json.dumps(coverage, indent=2) + "\n", encoding="utf-8")
    private_source = args.output.parent / "private-source"
    private_source.mkdir(exist_ok=True)
    (private_source / "source-manifests.json").write_text(
        json.dumps(source_manifests, indent=2) + "\n", encoding="utf-8")
    model_report = None
    if not args.no_models and not args.fixture:
        model_report = train_expanding_models(build_pregame_features(rows), args.output)
    manifest = refresh_manifest(args.output, model_report)
    # Space data bundles are exact copies and remain bound by the same manifest.
    for name in ("viewer-data", "article-data"):
        target = args.output.parent / name
        if target.exists():
            raise SystemExit(f"Use an empty output path: {target}")
        shutil.copytree(args.output, target)
    viewer_space = args.output.parent / "viewer-space"
    if viewer_space.exists():
        raise SystemExit(f"Use an empty output path: {viewer_space}")
    shutil.copytree(args.viewer_source, viewer_space)
    shutil.copytree(args.output, viewer_space / "data")
    print(json.dumps({"output": str(args.output), "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
