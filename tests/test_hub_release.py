import csv
import json
import tempfile
import unittest
from pathlib import Path

from knicks_history.hub_release import (
    build_monthly_summary,
    build_opponent_views,
    build_pregame_features,
    build_result_paths,
    enrich_games,
    load_current_release,
    load_publication_gate,
    publication_status,
    public_payload_allowed,
    resolve_team_dimension,
    safe_ratio,
    _normalize_javascript_assets,
    _space_readme,
    _validate_payload,
)


class HubReleaseTests(unittest.TestCase):
    def setUp(self):
        self.teams = {
            "1610612738": {"team_id": "1610612738", "team_name": "Boston Celtics", "team_abbrev": "BOS"},
            "1610612748": {"team_id": "1610612748", "team_name": "Miami Heat", "team_abbrev": "MIA"},
        }
        self.rows = []
        for index in range(7):
            opponent = "1610612738" if index % 2 == 0 else "1610612748"
            points, allowed = 100 + index, 96 + (index % 3)
            self.rows.append({
                "season": "2025-26", "season_type": "Regular Season",
                "game_id": f"002250{index:04d}", "team_id": "1610612752",
                "game_date": f"2025-{10 + index // 3:02d}-{10 + index:02d}",
                "matchup": "NYK vs. OPP" if index % 2 == 0 else "NYK @ OPP",
                "venue_side": "home" if index % 2 == 0 else "away",
                "wl": "W" if points > allowed else "L", "pts": str(points),
                "opponent_id": opponent, "opponent_pts": str(allowed),
                "point_margin": str(points - allowed), "fgm": "40", "fga": "80",
                "fg3m": "12", "fg3a": "30", "ftm": str(points - 92),
                "fta": "20", "oreb": "10", "dreb": "30", "reb": "40",
                "ast": str(20 + index), "stl": "7", "blk": "4", "tov": str(14 - index),
                "pf": "18", "source_sha256": "a" * 64,
            })
        self.games = enrich_games(self.rows, self.teams)

    def test_safe_ratio_zero_denominator_is_null(self):
        self.assertIsNone(safe_ratio(0, 0))

    def test_opponents_are_enriched_without_changing_game_id(self):
        self.assertEqual(self.games[0]["game_id"], "0022500000")
        self.assertEqual(self.games[0]["opponent_abbrev"], "BOS")
        self.assertEqual(self.games[0]["fg3_pct"], 0.4)

    def test_unknown_opponent_blocks_release(self):
        rows = [dict(self.rows[0], opponent_id="999")]
        with self.assertRaisesRegex(ValueError, "Unresolved opponent"):
            enrich_games(rows, self.teams)

    def test_pregame_features_exclude_current_game(self):
        features = build_pregame_features(self.games)
        self.assertEqual(features[0]["games_played_before"], 0)
        self.assertIsNone(features[0]["prior_5_pts"])
        self.assertEqual(features[1]["prior_5_pts"], self.games[0]["pts"])
        changed = [dict(row) for row in self.games]
        changed[3]["pts"] = 999
        changed_features = build_pregame_features(changed)
        self.assertEqual(features[3]["prior_5_pts"], changed_features[3]["prior_5_pts"])
        self.assertNotEqual(features[4]["prior_5_pts"], changed_features[4]["prior_5_pts"])

    def test_rolling_window_uses_only_five_previous_games(self):
        features = build_pregame_features(self.games)
        self.assertEqual(features[6]["history_games"], 5)
        self.assertEqual(features[6]["prior_5_pts"], 103.0)

    def test_shooting_aggregates_use_complete_pairs_only(self):
        changed = [dict(row) for row in self.games[:2]]
        changed[1]["fg3a"] = None
        features = build_pregame_features(changed)
        self.assertEqual(features[1]["prior_5_fg3_pct"], 0.4)
        monthly = build_monthly_summary(changed)
        self.assertEqual(monthly[0]["fg3_pct"], 0.4)

    def test_monthly_and_result_summaries_reconcile(self):
        monthly = build_monthly_summary(self.games)
        self.assertEqual(sum(row["games"] for row in monthly), len(self.games))
        paths = build_result_paths(self.games)
        first_stage = sum(row["weight"] for row in paths if row["source"] == "2025-26")
        second_stage = sum(row["weight"] for row in paths if row["target"] in ("Win", "Loss"))
        self.assertEqual(first_stage, len(self.games))
        self.assertEqual(second_stage, len(self.games))

    def test_opponent_views_reconcile_with_games(self):
        chord, grid, totals = build_opponent_views(self.games)
        self.assertEqual(sum(row["weight"] for row in chord), len(self.games))
        self.assertEqual(sum(row["weight"] for row in totals), len(self.games))
        self.assertEqual({row["opponent"] for row in grid}, {"BOS", "MIA"})
        for row in grid:
            for value in (row["home"], row["away"]):
                self.assertTrue(value is None or 0 <= value <= 1)

    def test_publication_gate_requires_complete_review(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gate.toml"
            path.write_text('redistribution_reviewed = true\nreviewed_by = ""\nreviewed_at = ""\nbasis = ""\ndataset_license = "other"\n')
            with self.assertRaisesRegex(ValueError, "ISO date"):
                load_publication_gate(path)
            path.write_text('redistribution_reviewed = true\nreviewed_by = "Reviewer"\nreviewed_at = "2026-11-16"\nbasis = "documented terms"\ndataset_license = "other"\n')
            self.assertTrue(load_publication_gate(path)["complete"])
            path.write_text('redistribution_reviewed = true\nreviewed_by = "Reviewer"\nreviewed_at = "not-a-date"\nbasis = "terms"\ndataset_license = "other"\n')
            with self.assertRaisesRegex(ValueError, "ISO date"):
                load_publication_gate(path)

    def test_publication_is_two_phase_and_requires_commit_pin(self):
        local = publication_status(True, False, "LOCAL_PREVIEW")
        self.assertTrue(local["dataset_publishable"])
        self.assertFalse(local["space_publishable"])
        pinned = publication_status(True, False, "a" * 40)
        self.assertTrue(pinned["dataset_publishable"])
        self.assertTrue(pinned["space_publishable"])
        dirty = publication_status(True, True, "a" * 40)
        self.assertFalse(dirty["dataset_publishable"])
        self.assertFalse(dirty["space_publishable"])
        mismatch = publication_status(True, False, "a" * 40, False, False)
        self.assertFalse(mismatch["dataset_publishable"])
        preview = publication_status(True, False, "a" * 40, force_preview=True)
        self.assertFalse(preview["dataset_publishable"])
        self.assertFalse(preview["space_publishable"])

    def test_research_policy_allows_only_synthetic_public_payloads(self):
        policy = {"research_only": True, "hub_publication_enabled": True,
                  "real_data_distribution_allowed": False,
                  "synthetic_demo_distribution_allowed": True}
        self.assertTrue(public_payload_allowed(policy, synthetic=True))
        self.assertFalse(public_payload_allowed(policy, synthetic=False))
        self.assertFalse(public_payload_allowed(
            dict(policy, real_data_distribution_allowed=True), synthetic=True))
        self.assertFalse(public_payload_allowed(
            dict(policy, hub_publication_enabled=False), synthetic=True))

    def test_space_card_uses_hub_supported_colors(self):
        readme = _space_readme("2024-25", "a" * 40)
        self.assertIn("colorFrom: blue", readme)
        self.assertIn("colorTo: indigo", readme)
        self.assertNotIn("colorTo: orange", readme)

    def test_javascript_assets_are_normalized_to_utf8(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "d3.v4.js"
            path.write_text("const label = 'Knicks';\r\n", encoding="utf-16")
            _normalize_javascript_assets(folder)
            raw = path.read_bytes()
            self.assertFalse(raw.startswith((b"\xff\xfe", b"\xfe\xff")))
            self.assertNotIn(b"\x00", raw)
            self.assertEqual(raw.decode("utf-8"), "const label = 'Knicks';\n")

    def test_team_dimension_uses_specific_then_common_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            common = root / "common.csv"
            common.write_text("common")
            self.assertEqual(resolve_team_dimension(root, "2021-22"), common)
            specific = root / "2021-22.csv"
            specific.write_text("specific")
            self.assertEqual(resolve_team_dimension(root, "2021-22"), specific)

    def test_current_release_selects_multiple_verified_seasons(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release_id = "20261116T000000000000Z-aaaaaaaa"
            release = root / "releases" / release_id
            release.mkdir(parents=True)
            (root / "CURRENT").write_text(release_id)
            (release / "manifest.json").write_text(json.dumps({"synthetic": False}))
            with (release / "team_games.csv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=("season", "game_id"))
                writer.writeheader()
                writer.writerows(({"season": "2019-20", "game_id": "a"},
                                  {"season": "2020-21", "game_id": "b"}))
            with (release / "coverage.csv").open("w", newline="") as stream:
                fields = ("season", "season_type", "expected_games", "status", "missing_opponent_rows")
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(({"season": "2019-20", "season_type": "Regular Season",
                                   "expected_games": 1, "status": "count_matches", "missing_opponent_rows": 0},
                                  {"season": "2020-21", "season_type": "Regular Season",
                                   "expected_games": 1, "status": "count_matches", "missing_opponent_rows": 0}))
            _, _, selected = load_current_release(root, ["2019-20", "2020-21"])
            self.assertEqual(list(selected), ["2019-20", "2020-21"])

    def test_closed_manifest_rejects_unexpected_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "known.txt").write_text("known")
            manifest = {"files": {"known.txt": {"sha256": "7117f9a540bb641872d362d2cf67481fc022a6d63283b88593e87b38e374d384", "bytes": 5}}}
            (root / "release-manifest.json").write_text(json.dumps(manifest))
            (root / "extra.txt").write_text("extra")
            _, errors = _validate_payload(root, ("known.txt",))
            self.assertIn("unexpected file: extra.txt", errors)


if __name__ == "__main__":
    unittest.main()
