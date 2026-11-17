import csv
import tempfile
import unittest
from pathlib import Path

from knicks_history.passing import FIELDS, aggregate_passing_edges, load_passing_edges


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


if __name__ == "__main__":
    unittest.main()
