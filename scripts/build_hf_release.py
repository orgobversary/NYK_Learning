"""Build a reviewable Hugging Face dataset and static Space release."""
import argparse
import json
from pathlib import Path

from knicks_history.hub_release import build_hub_release


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("data/live"))
    parser.add_argument("--season", action="append", dest="seasons",
                        help="season to include; repeat for a cumulative release")
    parser.add_argument("--space-season", help="included season shown by the Space")
    parser.add_argument("--output", type=Path, default=Path("build/huggingface"))
    parser.add_argument("--teams-dir", type=Path, default=Path("config/teams"))
    parser.add_argument("--gate", type=Path, default=Path("config/huggingface-publication.toml"))
    parser.add_argument("--space-source", type=Path, default=Path("huggingface/space"))
    parser.add_argument("--dataset-revision", default="LOCAL_PREVIEW")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="build a non-publishable local preview from a dirty source release")
    args = parser.parse_args()
    seasons = args.seasons or ["2025-26"]
    manifest = build_hub_release(args.root, seasons, args.output, args.teams_dir, args.gate,
                                 args.space_source, args.dataset_revision,
                                 args.space_season, args.allow_dirty)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
