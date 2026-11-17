"""Assemble a closed private-research release for immutable Bucket storage."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from knicks_history.research_store import repository_state, validate_closed_release, write_closed_manifest


def copy_source(source, destination):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-release", type=Path, required=True)
    parser.add_argument("--passing", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--space", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("build/research-releases"))
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    state = repository_state()
    if state["git_dirty"] and not args.allow_dirty:
        raise SystemExit("Private research staging requires a clean Git checkout")
    release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    output = args.output_root / release_id
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    copy_source(args.team_release, output / "team-games")
    copy_source(args.passing, output / "passing")
    copy_source(args.models, output / "models")
    copy_source(args.space, output / "space")
    metadata = {"release_id": release_id, "built_at": datetime.now(timezone.utc).isoformat(),
                "usage_scope": "private_research_only", "public_publishable": False,
                "private_preview_allowed": True, "synthetic": False,
                "builder_git_sha": state["git_sha"], "builder_git_dirty": state["git_dirty"]}
    write_closed_manifest(output, metadata)
    validate_closed_release(output)
    print(json.dumps({"release_id": release_id, "path": str(output)}, indent=2))


if __name__ == "__main__":
    main()
