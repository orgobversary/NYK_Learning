import csv
import tempfile
import unittest
import json
from pathlib import Path

from knicks_history.passing import (
    ASSIST_FIELDS,
    FIELDS,
    aggregate_assist_edges,
    aggregate_passing_edges,
    load_assist_edges,
    load_passing_edges,
    normalize_assist_events,
    normalize_passes_made,
    participant_ids,
)


class PassingLabTests(unittest.TestCase):
    def test_committed_fixture_is_synthetic_and_spans_five_seasons(self):
        rows = load_passing_edges("fixtures/passing-demo.csv", require_synthetic=True)
        edges, seasons = aggregate_passing_edges(rows)
        self.assertEqual(seasons, ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"])
        self.assertGreater(len(edges), 0)
        self.assertEqual(edges[0]["source"], "Passer · Aster Cole")
        self.assertEqual(edges[0]["target"], "Receiver · Beacon Reed")

    def test_real_rows_are_rejected_by_default_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "passing.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow({"season": "2024-25", "passer_player_id": "1",
                                 "passer_name": "One", "receiver_player_id": "2",
                                 "receiver_name": "Two", "passes": 10, "assists": 2,
                                 "games": 1, "source_url": "https://example.test/export",
                                 "rights_basis": "private authorized export", "synthetic": "false"})
            with self.assertRaisesRegex(ValueError, "synthetic state"):
                load_passing_edges(path, require_synthetic=True)

    def test_aggregate_requires_exactly_five_seasons(self):
        rows = load_passing_edges("fixtures/passing-demo.csv", require_synthetic=True)
        with self.assertRaisesRegex(ValueError, "exactly five seasons"):
            aggregate_passing_edges([row for row in rows if row["season"] != "2025-26"])

    def test_private_nba_response_is_normalized_without_pandas(self):
        participants_payload = {"resultSets": [{"name": "LeagueDashPlayerStats",
            "headers": ["PLAYER_ID", "PLAYER_NAME", "TEAM_ID"],
            "rowSet": [[1, "One", 1610612752], [2, "Two", 1610612752]]}]}
        participants = participant_ids(participants_payload)
        passing = {"resultSets": [{"name": "PassesMade",
            "headers": ["PLAYER_ID", "PASS_TEAMMATE_PLAYER_ID", "G", "PASS", "AST",
                        "FGM", "FGA", "FG3M", "FG3A"],
            "rowSet": [[1, 2, 20, 100, 12, 22, 45, 8, 20]]}]}
        raw = json.dumps(passing).encode()
        rows = normalize_passes_made(passing, "2024-25", "1", participants,
                                     "https://stats.nba.com/stats/playerdashptpass",
                                     "2026-11-17T00:00:00+00:00", "private research", raw)
        self.assertEqual(rows[0]["passes"], 100)
        self.assertFalse(rows[0]["synthetic"])

    def test_private_nba_response_rejects_unknown_receiver(self):
        payload = {"resultSets": [{"name": "PassesMade",
            "headers": ["PLAYER_ID", "PASS_TEAMMATE_PLAYER_ID", "G", "PASS", "AST",
                        "FGM", "FGA", "FG3M", "FG3A"],
            "rowSet": [[1, 3, 1, 2, 1, 1, 1, 0, 0]]}]}
        with self.assertRaisesRegex(ValueError, "unknown receiver"):
            normalize_passes_made(payload, "2024-25", "1", {"1": "One", "2": "Two"},
                                  "source", "time", "private research")

    def test_play_by_play_assists_reconcile_and_normalize(self):
        games = [{"game_id": "0020000001", "ast": "2"}]
        players = [{"player_id": "1", "name": "One Passer"},
                   {"player_id": "2", "name": "Two Scorer"}]
        events = [
            {"game_id": "0020000001", "team_id": "1610612752", "person_id": "1",
             "action_type": "Turnover", "description": "Passer Turnover", "shot_value": None},
            {"game_id": "0020000001", "team_id": "1610612752", "person_id": "2",
             "action_type": "Made Shot", "description": "Scorer 3PT Shot (Passer 1 AST)",
             "shot_value": 3},
            {"game_id": "0020000001", "team_id": "1610612752", "person_id": "2",
             "action_type": "Made Shot", "description": "Scorer Layup (Passer 2 AST)",
             "shot_value": 2},
        ]
        rows = normalize_assist_events(
            events, players, games, "2024-25", "https://example.test/events", "time",
            "private research", "a" * 64)
        self.assertEqual(rows[0]["assisted_makes"], 2)
        self.assertEqual(rows[0]["assisted_points"], 5)
        self.assertEqual(rows[0]["relation_type"], "assisted_made_basket")

    def test_play_by_play_assists_reject_incomplete_reconciliation(self):
        games = [{"game_id": "0020000001", "ast": "2"}]
        players = [{"player_id": "1", "name": "One Passer"},
                   {"player_id": "2", "name": "Two Scorer"}]
        events = [
            {"game_id": "0020000001", "team_id": "1610612752", "person_id": "1",
             "action_type": "Turnover", "description": "Passer Turnover", "shot_value": None},
            {"game_id": "0020000001", "team_id": "1610612752", "person_id": "2",
             "action_type": "Made Shot", "description": "Scorer Layup (Passer 1 AST)",
             "shot_value": 2},
        ]
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            normalize_assist_events(events, players, games, "2024-25", "source", "time",
                                    "private research", "b" * 64)

    def test_assist_contract_and_five_season_aggregation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "assists.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=ASSIST_FIELDS)
                writer.writeheader()
                for index, season in enumerate(
                        ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26"), 1):
                    writer.writerow({"season": season, "passer_player_id": "1",
                                     "passer_name": "One", "receiver_player_id": "2",
                                     "receiver_name": "Two", "games": index,
                                     "assisted_makes": index, "assisted_points": index * 2,
                                     "source_url": "https://example.test/events",
                                     "retrieved_at": "time", "source_sha256": "c" * 64,
                                     "rights_basis": "private research",
                                     "relation_type": "assisted_made_basket",
                                     "synthetic": "false"})
            rows = load_assist_edges(path)
            edges, seasons = aggregate_assist_edges(rows)
        self.assertEqual(len(seasons), 5)
        self.assertEqual(edges[0]["source"], "Assister · One")
        self.assertEqual(edges[0]["target"], "Scorer · Two")
        self.assertEqual(edges[0]["weight"], 15)


if __name__ == "__main__":
    unittest.main()
