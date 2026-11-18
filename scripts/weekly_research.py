# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = ["huggingface-hub>=1.1,<2"]
# ///
"""Weekly private research orchestration for a Bucket-mounted Hugging Face Job."""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BUCKET_ROOT = Path(os.environ.get("NYK_BUCKET_ROOT", "/research"))
REPO_URL = os.environ.get("NYK_REPO_URL", "https://github.com/orgobversary/NYK_Learning.git")
REPO_REF = os.environ.get("NYK_REPO_REF", "main")
SPACE_ID = os.environ.get("NYK_SPACE_ID", "obversarystudios/nyk_world")
RIGHTS_BASIS = os.environ.get(
    "NYK_PASSING_RIGHTS_BASIS",
    "private research under source access terms; redistribution not authorized",
)
TEAM_SEASONS = tuple(f"{year}-{(year + 1) % 100:02d}" for year in range(2017, 2026))
PASSING_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")


def run(command, cwd=None):
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def research_input_digest(team_games, passing):
    """Hash normalized facts while ignoring a timestamp-only source refresh."""
    value = hashlib.sha256()
    team_games, passing = Path(team_games), Path(passing)
    value.update(team_games.name.encode()); value.update(team_games.read_bytes())
    with passing.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if "retrieved_at" not in (reader.fieldnames or ()):
            raise ValueError("Passing contract requires retrieved_at")
        for row in reader:
            row.pop("retrieved_at")
            value.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
    return value.hexdigest()


def combine_passing(root, output, directory="assist_edges"):
    rows = []
    fields = None
    for season in PASSING_SEASONS:
        path = root / directory / f"{season}.csv"
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fields = fields or reader.fieldnames
            if reader.fieldnames != fields:
                raise ValueError("Passing schemas differ across seasons")
            rows.extend(reader)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def main():
    if not os.environ.get("HF_TOKEN"):
        raise SystemExit("HF_TOKEN is required for private preview publication")
    BUCKET_ROOT.mkdir(parents=True, exist_ok=True)
    workspace = BUCKET_ROOT / "workspace"
    data_root = workspace / "data" / "live"
    passing_root = workspace / "data" / "research" / "player_passing"
    registry = BUCKET_ROOT / "registry"; registry.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nyk-weekly-") as folder:
        root = Path(folder)
        repo = root / "repo"
        run(["git", "clone", "--depth", "1", "--branch", REPO_REF, REPO_URL, str(repo)])
        run(["uv", "pip", "install", "--python", sys.executable,
             "-e", ".[research,visualization]"], repo)
        run([sys.executable, "scripts/import_team_logs.py", "--start", "2018", "--end", "2026",
             "--playoffs-year", "2026", "--root", str(data_root)], repo)
        run([sys.executable, "-m", "knicks_history.cli", "build", "--root", str(data_root),
             "--expected", "config/expected-live.csv", "--parquet"], repo)
        for season in PASSING_SEASONS:
            path = passing_root / "assist_edges" / f"{season}.csv"
            if season != PASSING_SEASONS[-1] and path.exists():
                continue
            run([sys.executable, "scripts/fetch_assist_network.py", "--season", season,
                 "--root", str(passing_root), "--team-root", str(data_root),
                 "--rights-basis", RIGHTS_BASIS], repo)
        combined = root / "passing.csv"; combine_passing(passing_root, combined)
        current = (data_root / "CURRENT").read_text(encoding="utf-8").strip()
        team_release = data_root / "releases" / current
        # Release IDs and manifest timestamps change on every build. Hash the
        # normalized research inputs so a replay with identical rows is a no-op.
        input_hash = research_input_digest(team_release / "team_games.csv", combined)
        latest = registry / "latest-research.json"
        if latest.exists() and json.loads(latest.read_text()).get("input_sha256") == input_hash:
            print("No research input changes; keeping the current preview", flush=True)
            return
        feature_build = root / "feature-build"
        command = [sys.executable, "scripts/build_hf_release.py", "--root", str(data_root),
                   "--output", str(feature_build), "--dataset-revision", "PRIVATE_RESEARCH"]
        for season in TEAM_SEASONS:
            command += ["--season", season]
        command += ["--space-season", "2025-26", "--passing", str(combined)]
        run(command, repo)
        models = root / "models"
        run([sys.executable, "scripts/train_models.py", "--features",
             str(feature_build / "dataset" / "data" / "pregame_features"),
             "--output", str(models)], repo)
        final_build = root / "final-build"
        command[command.index(str(feature_build))] = str(final_build)
        command += ["--model-dir", str(models)]
        run(command, repo)
        run([sys.executable, "scripts/validate_hf_release.py", str(final_build)], repo)
        staged_root = root / "staged"
        run([sys.executable, "scripts/stage_research_release.py",
             "--team-release", str(team_release), "--passing", str(passing_root),
             "--models", str(models), "--space", str(final_build / "space"),
             "--output-root", str(staged_root)], repo)
        releases = list(staged_root.iterdir())
        if len(releases) != 1:
            raise RuntimeError("Expected exactly one staged release")
        release = releases[0]
        destination = BUCKET_ROOT / "releases" / release.name
        if destination.exists():
            raise FileExistsError(destination)
        shutil.copytree(release, destination)
        run(["hf", "upload", SPACE_ID, str(final_build / "space"), ".", "--type", "space",
             "--delete", "*", "--commit-message", f"Private research preview {release.name}"])
        pointer = {"release_id": release.name, "input_sha256": input_hash,
                   "builder_git_sha": json.loads((release / "research-manifest.json").read_text())["builder_git_sha"],
                   "space_id": SPACE_ID, "promoted_at": datetime.now(timezone.utc).isoformat()}
        payload = json.dumps(pointer, indent=2) + "\n"
        preview = registry / "latest-preview.json"
        research_temporary = registry / ".latest-research.tmp"
        preview_temporary = registry / ".latest-preview.tmp"
        research_temporary.write_text(payload, encoding="utf-8")
        preview_temporary.write_text(payload, encoding="utf-8")
        research_temporary.replace(latest)
        preview_temporary.replace(preview)
        print(json.dumps(pointer, indent=2))


if __name__ == "__main__":
    main()
