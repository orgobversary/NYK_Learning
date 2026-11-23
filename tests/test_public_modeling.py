import json
import tempfile
import unittest
from pathlib import Path

from knicks_history.public_modeling import train_expanding_models


def feature_rows():
    rows = []
    for season_index, season in enumerate(("2021-22", "2022-23", "2023-24")):
        for game in range(1, 13):
            win = (game + season_index) % 2
            margin = 7 if win else -5
            rows.append({
                "game_key": f"{season}-{game}", "season": season,
                "season_type": "Regular Season", "game_number": game + 5,
                "game_date": f"{season[:4]}-12-{game:02d}",
                "opponent_abbrev": ("BOS", "MIA", "PHI")[game % 3],
                "venue_side": "home" if game % 2 else "away", "days_rest": 1 + game % 3,
                "games_played_before": game + 4,
                "prior_5_points": 100 + game, "prior_5_opponent_points": 99 + game % 4,
                "prior_5_margin": margin / 2, "prior_5_win_pct": .4 + .1 * win,
                "prior_10_points": 99 + game / 2, "prior_10_opponent_points": 98 + game % 3,
                "prior_10_margin": margin / 3, "prior_10_win_pct": .45 + .05 * win,
                "target_win": win, "target_point_margin": margin,
            })
    return rows


class PublicModelingTests(unittest.TestCase):
    def test_expanding_models_emit_only_out_of_sample_predictions(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            self.skipTest("Install the ml extra")
        with tempfile.TemporaryDirectory() as folder:
            report = train_expanding_models(feature_rows(), Path(folder))
            self.assertEqual(report["first_test_season"], "2023-24")
            self.assertEqual(report["folds"][0]["train_through"], "2022-23")
            predictions = (Path(folder) / "model_predictions.csv").read_text()
            self.assertIn("2023-24", predictions)
            self.assertNotIn("2021-22", predictions)
            metrics = json.loads((Path(folder) / "model_metrics.json").read_text())
            self.assertIn("dummy_accuracy", metrics["folds"][0])
            self.assertIn("dummy_log_loss", metrics["folds"][0])
            self.assertIn("dummy_brier", metrics["folds"][0])
            self.assertIn("dummy_margin_mae", metrics["folds"][0])
            self.assertIn("dummy_margin_rmse", metrics["folds"][0])


if __name__ == "__main__":
    unittest.main()
