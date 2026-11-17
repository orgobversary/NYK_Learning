import csv
import tempfile
import unittest
from pathlib import Path

from scripts.weekly_research import research_input_digest


class WeeklyResearchTests(unittest.TestCase):
    def test_digest_ignores_retrieval_time_but_detects_fact_changes(self):
        fields = ("season", "assisted_makes", "retrieved_at", "source_sha256")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            team = root / "team_games.csv"
            passing = root / "passing.csv"
            team.write_text("game_id,pts\n001,100\n", encoding="utf-8")

            def write(assists, retrieved_at):
                with passing.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    writer.writerow({"season": "2025-26", "assisted_makes": assists,
                                     "retrieved_at": retrieved_at,
                                     "source_sha256": "a" * 64})

            write("12", "first")
            original = research_input_digest(team, passing)
            write("12", "second")
            self.assertEqual(original, research_input_digest(team, passing))
            write("13", "second")
            self.assertNotEqual(original, research_input_digest(team, passing))


if __name__ == "__main__":
    unittest.main()
