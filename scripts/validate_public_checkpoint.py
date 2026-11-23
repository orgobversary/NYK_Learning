"""Validate separation and checksums for a generated public checkpoint."""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

FORBIDDEN_FIELDS = {"source_game_key", "provider_game_id", "api_key", "team_id"}
FORBIDDEN_TEXT = ("BALLDONTLIE_API_KEY", "HF_TOKEN", "/var/home/", "nba_api.stats")


def validate(root, allow_synthetic_fixture=False):
    root = Path(root)
    dataset = root / "analytics"
    manifest_path = dataset / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    errors = []
    source_partition_keys = set()
    if manifest.get("provider") != "balldontlie":
        errors.append("public checkpoint must use BALLDONTLIE")
    if manifest.get("synthetic") is not False and not allow_synthetic_fixture:
        errors.append("public checkpoint must contain real data")
    if manifest.get("synthetic") is False and not (dataset / "coverage.json").is_file():
        errors.append("real public checkpoint is missing coverage evidence")
    if not (dataset / "README.md").is_file():
        errors.append("public dataset card is missing")
    expected = set(manifest.get("files", {}))
    actual = {path.name for path in dataset.iterdir()
              if path.is_file() and path.name != manifest_path.name}
    if expected != actual:
        errors.append(f"closed file set differs: expected={sorted(expected)} actual={sorted(actual)}")
    for name in sorted(expected & actual):
        digest = hashlib.sha256((dataset / name).read_bytes()).hexdigest()
        if digest != manifest["files"][name]["sha256"]:
            errors.append(f"checksum mismatch: {name}")
    for path in dataset.glob("*.csv"):
        with path.open(newline="", encoding="utf-8") as stream:
            fields = set(next(csv.reader(stream), []))
        leaked = fields & FORBIDDEN_FIELDS
        if leaked:
            errors.append(f"forbidden fields in {path.name}: {sorted(leaked)}")
    for path in dataset.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in FORBIDDEN_TEXT:
                if marker in text:
                    errors.append(f"forbidden marker in {path.name}: {marker}")
            if re.search(r"(?:sk-|hf_)[A-Za-z0-9_-]{16,}", text):
                errors.append(f"credential-like value in {path.name}")
    source_path = root / "private-source" / "source-manifests.json"
    if not source_path.is_file():
        errors.append("private source manifest is missing")
    else:
        source_manifests = json.loads(source_path.read_text())
        source_digest = hashlib.sha256(
            json.dumps(source_manifests, sort_keys=True).encode()
        ).hexdigest()
        if source_digest != manifest.get("source_manifest_sha256"):
            errors.append("private source manifest digest does not match public manifest")
        if manifest.get("synthetic") is False:
            referenced_raw = set()
            raw_directory = root / "private-source" / "raw"
            for source in source_manifests:
                source_key = (source.get("season"), source.get("season_type"))
                if source_key in source_partition_keys:
                    errors.append(f"duplicate source partition manifest: {source_key}")
                source_partition_keys.add(source_key)
                if source.get("provider") != "balldontlie" or source.get("fixture"):
                    errors.append("real checkpoint contains a non-production source manifest")
                expected_provider_types = (["playoffs"] if source.get("season_type") == "Playoffs"
                                           else ["regular", "ist"])
                if source.get("provider_season_types") != expected_provider_types:
                    errors.append(f"provider season types differ for {source_key}")
                pages = source.get("pages")
                if not isinstance(pages, list) or not pages:
                    errors.append("real source partition has no raw page evidence")
                    continue
                observed_provider_types = set()
                for page in pages:
                    name = page.get("file")
                    if not name:
                        errors.append("raw source page is missing its file reference")
                        continue
                    if page.get("provider_season_type") not in expected_provider_types:
                        errors.append(f"raw source page has an unexpected season type: {name}")
                    else:
                        observed_provider_types.add(page.get("provider_season_type"))
                    referenced_raw.add(name)
                    raw_path = raw_directory / name
                    if not raw_path.is_file():
                        errors.append(f"referenced raw source page is missing: {name}")
                        continue
                    raw = raw_path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != page.get("sha256"):
                        errors.append(f"raw source checksum mismatch: {name}")
                    if len(raw) != page.get("bytes"):
                        errors.append(f"raw source byte count mismatch: {name}")
                if observed_provider_types != set(expected_provider_types):
                    errors.append(f"raw source page types are incomplete for {source_key}")
            actual_raw = ({path.name for path in raw_directory.iterdir() if path.is_file()}
                          if raw_directory.is_dir() else set())
            if actual_raw != referenced_raw:
                errors.append("private raw source file set differs from source manifests")

    games_path = dataset / "games.csv"
    games = []
    if games_path.is_file():
        with games_path.open(newline="", encoding="utf-8") as stream:
            games = list(csv.DictReader(stream))
        seasons = sorted({row["season"] for row in games})
        if seasons != manifest.get("seasons"):
            errors.append("game seasons do not match release manifest")
        regular = sum(row["season_type"] == "Regular Season" for row in games)
        playoffs = sum(row["season_type"] == "Playoffs" for row in games)
        if regular != manifest.get("regular_season_games"):
            errors.append("regular-season game count does not match release manifest")
        if playoffs != manifest.get("playoff_games"):
            errors.append("playoff game count does not match release manifest")
    if manifest.get("synthetic") is False:
        coverage_path = dataset / "coverage.json"
        if coverage_path.is_file():
            coverage = json.loads(coverage_path.read_text())
            coverage_keys = set()
            for item in coverage:
                key = (item.get("season"), item.get("season_type"))
                if key in coverage_keys:
                    errors.append(f"duplicate coverage partition: {key}")
                coverage_keys.add(key)
                observed = sum(
                    (row.get("season"), row.get("season_type")) == key
                    for row in games
                )
                if observed != item.get("observed_games"):
                    errors.append(f"coverage does not reconcile for {key}")
                if item.get("observed_games") != item.get("expected_games"):
                    errors.append(f"coverage expectation is not satisfied for {key}")
                if item.get("status") != "count_matches":
                    errors.append(f"coverage status is not approved for {key}")
            if coverage_keys != source_partition_keys:
                errors.append("coverage partitions do not match private source manifests")
        required_model_files = {"model_predictions.csv", "model_metrics.json"}
        if not required_model_files.issubset(actual):
            errors.append("real checkpoint is missing required model artifacts")
    for bundle in (root / "viewer-data", root / "article-data"):
        if not bundle.is_dir():
            errors.append(f"missing bundle: {bundle.name}")
            continue
        bundle_files = {path.name for path in bundle.iterdir() if path.is_file()}
        dataset_files = {path.name for path in dataset.iterdir() if path.is_file()}
        if bundle_files != dataset_files:
            errors.append(f"{bundle.name} does not match analytics payload")
    viewer_data = root / "viewer-space" / "data"
    if not viewer_data.is_dir():
        errors.append("staged viewer Space is missing its data bundle")
    elif {path.name for path in viewer_data.iterdir() if path.is_file()} != {
            path.name for path in dataset.iterdir() if path.is_file()}:
        errors.append("staged viewer Space data does not match analytics payload")
    if errors:
        raise ValueError("Public checkpoint validation failed:\n- " + "\n- ".join(errors))
    return {"provider": manifest["provider"], "files": len(actual),
            "seasons": manifest["seasons"]}


if __name__ == "__main__":
    try:
        print(json.dumps(validate(sys.argv[1], "--allow-synthetic-fixture" in sys.argv[2:]), indent=2))
    except (IndexError, ValueError) as exc:
        raise SystemExit(str(exc))
