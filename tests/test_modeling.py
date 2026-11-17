import tempfile
import unittest
from pathlib import Path

from knicks_history.modeling import chronological_split, train_models


def rows():
    seasons = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22",
               "2022-23", "2023-24", "2024-25", "2025-26"]
    output = []
    index = 0
    for season in seasons:
        for game in range(12):
            index += 1
            output.append({"season": season, "game_id": f"{index:010d}",
                "game_date": f"{season[:4]}-12-{game + 1:02d}", "history_games": 5,
                "games_played_before": game + 5, "season_to_date_win_pct": .45 + .01 * (game % 5),
                "prior_5_pts": 100 + game, "prior_5_opponent_pts": 99 + game % 4,
                "prior_5_point_margin": (game % 7) - 3, "prior_5_reb": 41 + game % 3,
                "prior_5_ast": 22 + game % 4, "prior_5_tov": 13 - game % 3,
                "prior_5_fg_pct": .45 + .001 * game, "prior_5_fg3_pct": .34 + .002 * game,
                "prior_5_ft_pct": .78, "opponent_abbrev": "BOS" if game % 2 else "MIA",
                "venue_side": "home" if game % 2 else "away",
                "target_win": game % 2, "target_point_margin": 7 if game % 2 else -5})
    return output


class ModelingTests(unittest.TestCase):
    def test_chronological_split_never_moves_test_rows_into_training(self):
        groups = chronological_split(rows())
        self.assertEqual({row["season"] for row in groups["validation"]}, {"2023-24"})
        self.assertEqual({row["season"] for row in groups["test"]}, {"2024-25", "2025-26"})
        self.assertNotIn("2025-26", {row["season"] for row in groups["train"]})

    def test_incomplete_history_is_excluded(self):
        source = rows(); source[0]["history_games"] = 4
        groups = chronological_split(source)
        self.assertEqual(sum(map(len, groups.values())), len(source) - 1)

    def test_training_writes_inspectable_artifacts(self):
        try:
            import sklearn  # noqa: F401
            import polars  # noqa: F401
        except ImportError:
            self.skipTest("Install the ml extra")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "model"
            result = train_models(rows(), output)
            self.assertIn("log_loss", result["metrics"]["classification"])
            for name in ("model-run.json", "metrics.json", "predictions.parquet",
                         "coefficients.parquet", "MODEL_CARD.md", "win-probability.joblib",
                         "point-margin.joblib"):
                self.assertTrue((output / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
