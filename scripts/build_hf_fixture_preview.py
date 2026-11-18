"""Build a clearly synthetic Space fixture for CI; never a publishable release."""
import argparse
import shutil
from pathlib import Path

from knicks_history.hub_release import (
    _data_contract,
    _synthetic_dataset_readme,
    _generate_d3,
    _generate_previews,
    _generate_model_chapter,
    _generate_passing_chapter,
    _generate_synthetic_playoff_placeholder,
    _space_index,
    _space_readme,
    _write_json,
    _write_parquet,
    _write_payload_manifest,
    _write_story_manifest,
    build_monthly_summary,
    build_pregame_features,
    build_result_paths,
    enrich_games,
    load_publication_gate,
    public_payload_allowed,
    repository_state,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-revision", default="LOCAL_PREVIEW")
    parser.add_argument("--publishable", action="store_true",
                        help="mark a clean synthetic build for policy-controlled Hub publication")
    parser.add_argument("--policy", type=Path,
                        default=Path("config/huggingface-publication.toml"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use an empty output directory")
    teams = {
        "1610612738": {"team_id": "1610612738", "team_name": "Invented Boston", "team_abbrev": "BOS", "source_url": "synthetic"},
        "1610612748": {"team_id": "1610612748", "team_name": "Invented Miami", "team_abbrev": "MIA", "source_url": "synthetic"},
    }
    rows = []
    dates = ("2024-10-10", "2024-11-12", "2024-12-14", "2025-01-16",
             "2025-02-18", "2025-03-20", "2025-04-10")
    for index in range(7):
        opponent = "1610612738" if index % 2 == 0 else "1610612748"
        points = 100 + index
        allowed = 96 + index % 3 if index % 3 else 108 + index
        rows.append({"season": "2024-25", "season_type": "Regular Season",
                     "game_id": f"002240{index:04d}", "team_id": "1610612752",
                     "game_date": dates[index], "matchup": "SYNTHETIC",
                     "venue_side": "home" if index % 2 == 0 else "away",
                     "wl": "W" if points > allowed else "L",
                     "pts": str(points), "opponent_id": opponent, "opponent_pts": str(allowed),
                     "point_margin": str(points - allowed), "fgm": "40", "fga": "80",
                     "fg3m": "12", "fg3a": str(30 + index), "ftm": str(points - 92), "fta": "20",
                     "oreb": "10", "dreb": "30", "reb": "40", "ast": str(20 + index),
                     "stl": "7", "blk": "4", "tov": str(14 - index), "pf": "18",
                     "source_sha256": "synthetic"})
    games = enrich_games(rows, teams)
    features, monthly = build_pregame_features(games), build_monthly_summary(games)
    dataset, space = args.output / "dataset", args.output / "space"
    paths = {}
    for name, values in {"games": games, "pregame_features": features,
                         "monthly_summary": monthly,
                         "teams": [dict(row, season="2024-25") for row in teams.values()]}.items():
        path = dataset / "data" / name / "2024-25.parquet"
        _write_parquet(path, values)
        paths[name] = [path]
    _write_json(dataset / "metadata/data-contract.json", _data_contract(paths))
    _write_json(dataset / "metadata/seasons/2024-25/coverage.json",
                {"season": "2024-25", "season_type": "Regular Season",
                 "observed_games": 7, "expected_games": 7, "status": "count_matches",
                 "count_source": "synthetic CI fixture", "missing_opponent_rows": 0})
    _write_json(dataset / "metadata/seasons/2024-25/source-manifest.json",
                {"synthetic": True, "release_id": "SYNTHETIC-CI-ONLY"})
    (dataset / "README.md").write_text(_synthetic_dataset_readme("2024-25", 7), encoding="utf-8")
    state = repository_state()
    if args.publishable:
        policy = load_publication_gate(args.policy)
        if state["git_dirty"]:
            raise ValueError("A publishable synthetic release requires a clean repository")
        if not public_payload_allowed(policy, synthetic=True):
            raise ValueError("The checked-in policy does not allow synthetic publication")
    dataset_publishable = args.publishable
    space_publishable = args.publishable and len(args.dataset_revision) == 40
    metadata = {"format_version": 1, "built_at": "2024-01-01T00:00:00+00:00",
                "seasons": ["2024-25"], "rows": 7, "synthetic": True,
                "usage_scope": "public_synthetic_demo", "builder_git_sha": state["git_sha"],
                "builder_git_dirty": state["git_dirty"]}
    _write_payload_manifest(dataset, {**metadata, "dataset_publishable": dataset_publishable,
                                      "space_publishable": False, "publishable": False,
                                      "payload": "dataset"})
    space.mkdir()
    source = Path("huggingface/space")
    shutil.copytree(source / "styles", space / "styles")
    shutil.copytree(source / "scripts", space / "scripts")
    template = (source / "index.template.html").read_text(encoding="utf-8")
    dataset_id = "obversarystudios/nyk-world-data" if space_publishable else None
    (space / "README.md").write_text(
        _space_readme("2024-25", args.dataset_revision, dataset_id), encoding="utf-8")
    _generate_d3(games, features, monthly, build_result_paths(games), space / "charts")
    _generate_previews(games, features, monthly, space / "previews")
    passing = _generate_passing_chapter(Path("fixtures/passing-demo.csv"),
                                        space / "charts", space / "previews")
    playoffs = _generate_synthetic_playoff_placeholder(space / "charts", space / "previews")
    model = _generate_model_chapter(games, features, None, space / "charts", space / "previews")
    _write_story_manifest(space, "2024-25", args.dataset_revision, playoffs, passing, model, True)
    (space / "index.html").write_text(
        _space_index(template, "2024-25", args.dataset_revision, games, playoffs,
                     "SYNTHETIC DEMONSTRATION", dataset_id),
        encoding="utf-8")
    from knicks_history.hub_release import digest, MANIFEST_NAME
    _write_payload_manifest(space, {**metadata, "dataset_publishable": dataset_publishable,
                                    "space_publishable": space_publishable,
                                    "publishable": space_publishable, "payload": "space",
                                    "dataset_id": dataset_id,
                                    "dataset_revision": args.dataset_revision,
                                    "dataset_manifest_sha256": digest(dataset / MANIFEST_NAME)})
    _write_json(args.output / "release.json", {"synthetic": True, "rows": 7})


if __name__ == "__main__":
    main()
