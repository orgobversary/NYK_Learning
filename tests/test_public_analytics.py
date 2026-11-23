import csv
import hashlib
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path

from knicks_history.public_analytics import (
    API_ROOT, build_monthly_summary, build_opponent_summary, build_playoff_series,
    build_pregame_features, fetch_partition,
    normalize_games, public_games, write_public_release,
)
from scripts.build_public_checkpoint import refresh_manifest, validate_coverage, validate_live_policy
from scripts.validate_public_checkpoint import validate as validate_checkpoint

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "balldontlie-games-demo.json"


class PublicAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text())
        self.rows = normalize_games(self.payload, "2024-25", "Regular Season")

    def test_normalizes_home_and_away_scores(self):
        self.assertEqual([row["venue_side"] for row in self.rows], ["home", "away"])
        self.assertEqual([row["result"] for row in self.rows], ["L", "W"])
        self.assertEqual([row["point_margin"] for row in self.rows], [-9, 5])

    def test_provider_route_is_scoped_to_nba_v1(self):
        self.assertEqual(API_ROOT, "https://api.balldontlie.io/nba/v1")

    def test_fetch_retries_rate_limit_and_throttles_final_page(self):
        raw = FIXTURE.read_bytes()
        cup_final = json.loads(FIXTURE.read_text())["data"][0]
        cup_final.update({"id": 999999, "date": "2024-12-17",
                          "ist_stage": "Championship"})
        ist_raw = json.dumps({"data": [cup_final], "meta": {}}).encode()
        calls, waits = [], []

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return self.body

        def request(req, timeout):
            calls.append((req, timeout))
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 429, "rate limited", {"Retry-After": "2"}, None)
            return Response(ist_raw if "season_type=ist" in req.full_url else raw)

        rows, manifest = fetch_partition(
            "test-key", "2024-25", "Regular Season", request=request,
            delay=.1, sleep=waits.append)
        self.assertEqual(len(rows), 2)
        self.assertEqual(manifest["rows"], 2)
        self.assertEqual(waits, [2.0, .1, .1])
        self.assertEqual(calls[-1][1], 45)
        self.assertEqual(calls[-1][0].get_header("Authorization"), "test-key")
        self.assertIn("/nba/v1/games?", calls[-1][0].full_url)
        self.assertIn("season_type=ist", calls[-1][0].full_url)
        self.assertEqual(manifest["provider_season_types"], ["regular", "ist"])
        self.assertEqual(manifest["excluded_nba_cup_championship_games"], 1)

    def test_ist_games_join_regular_season_but_cup_final_is_excluded(self):
        group_game = json.loads(FIXTURE.read_text())["data"][0]
        group_game["season_type"] = "ist"
        group_game["ist_stage"] = "East Group A"
        rows = normalize_games({"data": [group_game]}, "2024-25", "Regular Season")
        self.assertEqual(rows[0]["season_type"], "Regular Season")
        group_game["ist_stage"] = "Championship"
        with self.assertRaises(ValueError):
            normalize_games({"data": [group_game]}, "2024-25", "Regular Season")

    def test_public_rows_exclude_provider_identifiers(self):
        rows = public_games(self.rows)
        self.assertNotIn("source_game_key", rows[0])
        self.assertNotIn("id", rows[0])
        self.assertEqual([row["game_number"] for row in rows], [1, 2])

    def test_features_use_prior_games_only(self):
        features = build_pregame_features(self.rows)
        self.assertIsNone(features[0]["prior_5_margin"])
        self.assertEqual(features[1]["prior_5_margin"], -9)
        self.assertEqual(features[1]["days_rest"], 2)
        self.assertEqual(features[1]["target_point_margin"], 5)

    def test_summaries_are_derived(self):
        monthly = build_monthly_summary(self.rows)
        self.assertEqual(monthly[0]["games"], 2)
        self.assertEqual(monthly[0]["mean_margin"], -2)
        opponents = build_opponent_summary(self.rows)
        self.assertEqual({row["opponent_abbrev"] for row in opponents}, {"BOS", "DET"})

    def test_playoff_series_labels_start_at_round_one(self):
        rows = []
        for index in range(8):
            row = dict(self.rows[0 if index < 4 else 1])
            row.update({"source_game_key": f"playoff:{index}",
                        "game_key": f"playoff-{index}",
                        "game_date": f"2025-05-{index + 1:02d}",
                        "season_type": "Playoffs"})
            rows.append(row)
        series = build_playoff_series(rows)
        self.assertEqual([item["round"] for item in series], ["Round One", "Conference Semifinals"])

    def test_nonfinal_and_duplicate_games_fail(self):
        broken = json.loads(FIXTURE.read_text())
        broken["data"][0]["status"] = "2nd Qtr"
        broken["data"][0]["status_state"] = "in"
        with self.assertRaises(ValueError):
            normalize_games(broken)
        duplicate = json.loads(FIXTURE.read_text())
        duplicate["data"].append(duplicate["data"][0])
        with self.assertRaises(ValueError):
            normalize_games(duplicate)

    def test_closed_release_contains_only_approved_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "release"
            manifest = write_public_release(
                self.rows, destination, [{"sha256": "a" * 64}],
                {"reviewed_at": "2026-11-21", "basis": "provider terms reviewed"})
            self.assertFalse(manifest["synthetic"])
            self.assertEqual(manifest["provider"], "balldontlie")
            with (destination / "games.csv").open(newline="") as stream:
                header = next(csv.reader(stream))
            self.assertNotIn("source_game_key", header)
            self.assertEqual(set(manifest["files"]), {
                "README.md", "games.csv", "monthly_summary.csv", "opponent_summary.csv",
                "playoff_series.csv", "pregame_features.csv", "season_summary.csv"})
            card = (destination / "README.md").read_text()
            self.assertIn("config_name: games", card)
            self.assertIn("not affiliated with or endorsed", card)

    def test_checkpoint_binds_private_source_manifest_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_manifests = [{"provider": "balldontlie", "fixture": True,
                                 "sha256": "a" * 64}]
            write_public_release(
                self.rows, root / "analytics", source_manifests,
                {"reviewed_at": "2000-01-01", "basis": "offline fixture"},
                synthetic=True)
            private = root / "private-source"
            private.mkdir()
            source_path = private / "source-manifests.json"
            source_path.write_text(json.dumps(source_manifests), encoding="utf-8")
            shutil.copytree(root / "analytics", root / "viewer-data")
            shutil.copytree(root / "analytics", root / "article-data")
            (root / "viewer-space").mkdir()
            shutil.copytree(root / "analytics", root / "viewer-space" / "data")
            result = validate_checkpoint(root, allow_synthetic_fixture=True)
            self.assertEqual(result["provider"], "balldontlie")
            source_path.write_text(json.dumps([{"tampered": True}]), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_checkpoint(root, allow_synthetic_fixture=True)

    def test_real_checkpoint_reconciles_raw_pages_coverage_and_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw_regular = FIXTURE.read_bytes()
            raw_ist = json.dumps({"data": [], "meta": {}}).encode()
            pages = []
            for name, provider_type, raw in (
                    ("regular.json", "regular", raw_regular),
                    ("ist.json", "ist", raw_ist)):
                pages.append({"file": name, "provider_season_type": provider_type,
                              "page_number": 1, "sha256": hashlib.sha256(raw).hexdigest(),
                              "bytes": len(raw)})
            sources = [{"provider": "balldontlie", "season": "2024-25",
                        "season_type": "Regular Season",
                        "provider_season_types": ["regular", "ist"],
                        "excluded_nba_cup_championship_games": 0,
                        "pages": pages, "rows": 2}]
            write_public_release(
                self.rows, root / "analytics", sources,
                {"reviewed_at": "2000-01-01", "basis": "offline contract"})
            coverage = [{"season": "2024-25", "season_type": "Regular Season",
                         "expected_games": 2, "observed_games": 2,
                         "basis": "test", "status": "count_matches"}]
            (root / "analytics" / "coverage.json").write_text(
                json.dumps(coverage), encoding="utf-8")
            (root / "analytics" / "model_predictions.csv").write_text(
                "game_key,season\n", encoding="utf-8")
            (root / "analytics" / "model_metrics.json").write_text(
                "{}\n", encoding="utf-8")
            refresh_manifest(root / "analytics")
            private = root / "private-source"
            raw_dir = private / "raw"
            raw_dir.mkdir(parents=True)
            (raw_dir / "regular.json").write_bytes(raw_regular)
            (raw_dir / "ist.json").write_bytes(raw_ist)
            (private / "source-manifests.json").write_text(
                json.dumps(sources), encoding="utf-8")
            shutil.copytree(root / "analytics", root / "viewer-data")
            shutil.copytree(root / "analytics", root / "article-data")
            (root / "viewer-space").mkdir()
            shutil.copytree(root / "analytics", root / "viewer-space" / "data")
            result = validate_checkpoint(root)
            self.assertEqual(result["seasons"], ["2024-25"])
            (raw_dir / "ist.json").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                validate_checkpoint(root)

    def test_coverage_requires_every_partition_and_exact_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "coverage.csv"
            path.write_text(
                "season,season_type,expected_games,basis\n"
                "2024-25,Regular Season,2,test\n"
                "2024-25,Playoffs,0,test\n", encoding="utf-8")
            source = [{"season": "2024-25", "season_type": "Regular Season"},
                      {"season": "2024-25", "season_type": "Playoffs"}]
            evidence = validate_coverage(self.rows, source, path, 2024, 2024)
            self.assertEqual([row["status"] for row in evidence],
                             ["count_matches", "count_matches"])
            path.write_text(
                "season,season_type,expected_games,basis\n"
                "2024-25,Regular Season,82,test\n"
                "2024-25,Playoffs,0,test\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_coverage(self.rows, source, path, 2024, 2024)

    def test_live_policy_closes_scope_and_review_metadata(self):
        policy = Path(__file__).resolve().parents[1] / "config" / "public-analytics.toml"
        parsed = validate_live_policy(
            policy, 2017, 2025, "2000-01-01", "named source review")
        self.assertEqual(parsed["initial_scope"]["first_season"], "2017-18")
        with self.assertRaises(ValueError):
            validate_live_policy(policy, 2018, 2025, "2000-01-01", "review")
        with self.assertRaises(ValueError):
            validate_live_policy(policy, 2017, 2025, "not-a-date", "review")


if __name__ == "__main__":
    unittest.main()
