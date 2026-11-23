"""Leakage-resistant expanding-window models for the public game-only release."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

NUMERIC = (
    "days_rest", "games_played_before", "prior_5_points",
    "prior_5_opponent_points", "prior_5_margin", "prior_5_win_pct",
    "prior_10_points", "prior_10_opponent_points", "prior_10_margin",
    "prior_10_win_pct",
)
CATEGORICAL = ("opponent_abbrev", "venue_side")


def _rmse(actual, predicted):
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))


def _features(rows):
    return [{name: row.get(name) for name in NUMERIC + CATEGORICAL} for row in rows]


def train_expanding_models(rows, destination):
    """Fit only on prior seasons and emit out-of-sample predictions."""
    try:
        import pandas as pd
        from sklearn.compose import ColumnTransformer
        from sklearn.dummy import DummyClassifier, DummyRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.metrics import (accuracy_score, brier_score_loss, log_loss,
                                     mean_absolute_error)
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:
        raise RuntimeError("Install the ml extra to build public model outputs") from exc

    eligible = [dict(row) for row in rows
                if row["season_type"] == "Regular Season" and
                int(row["games_played_before"]) >= 5]
    seasons = sorted({row["season"] for row in eligible})
    if len(seasons) < 3:
        raise ValueError("Expanding models require at least three seasons")

    def processor():
        numeric = Pipeline([("impute", SimpleImputer(strategy="median")),
                            ("scale", StandardScaler())])
        categorical = Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                                ("encode", OneHotEncoder(handle_unknown="ignore"))])
        return ColumnTransformer([("numeric", numeric, list(NUMERIC)),
                                  ("categorical", categorical, list(CATEGORICAL))])

    predictions = []
    fold_metrics = []
    for index in range(2, len(seasons)):
        test_season = seasons[index]
        train = [row for row in eligible if row["season"] in seasons[:index]]
        test = [row for row in eligible if row["season"] == test_season]
        if not train or not test or len({row["target_win"] for row in train}) < 2:
            raise ValueError(f"Insufficient classes for expanding fold {test_season}")
        x_train, x_test = pd.DataFrame(_features(train)), pd.DataFrame(_features(test))
        y_win = [int(row["target_win"]) for row in train]
        y_margin = [int(row["target_point_margin"]) for row in train]
        actual_win = [int(row["target_win"]) for row in test]
        actual_margin = [int(row["target_point_margin"]) for row in test]

        classifier = Pipeline([("features", processor()),
                               ("model", LogisticRegression(C=1.0, max_iter=2000,
                                                            random_state=52))])
        classifier.fit(x_train, y_win)
        probability = classifier.predict_proba(x_test)[:, 1]
        prediction = (probability >= .5).astype(int)
        dummy_classifier = DummyClassifier(strategy="prior").fit(x_train, y_win)
        dummy_probability = dummy_classifier.predict_proba(x_test)[:, 1]
        dummy_prediction = dummy_classifier.predict(x_test)

        regressor = Pipeline([("features", processor()), ("model", Ridge(alpha=10.0))])
        regressor.fit(x_train, y_margin)
        margin_prediction = regressor.predict(x_test)
        dummy_regressor = DummyRegressor(strategy="mean").fit(x_train, y_margin)
        dummy_margin = dummy_regressor.predict(x_test)

        fold_metrics.append({
            "test_season": test_season, "train_through": seasons[index - 1],
            "train_rows": len(train), "test_rows": len(test),
            "accuracy": round(float(accuracy_score(actual_win, prediction)), 6),
            "dummy_accuracy": round(float(accuracy_score(actual_win,
                                                           dummy_prediction)), 6),
            "log_loss": round(float(log_loss(actual_win, probability, labels=[0, 1])), 6),
            "dummy_log_loss": round(float(log_loss(actual_win, dummy_probability,
                                                     labels=[0, 1])), 6),
            "brier": round(float(brier_score_loss(actual_win, probability)), 6),
            "dummy_brier": round(float(brier_score_loss(actual_win,
                                                           dummy_probability)), 6),
            "margin_mae": round(float(mean_absolute_error(actual_margin,
                                                            margin_prediction)), 6),
            "dummy_margin_mae": round(float(mean_absolute_error(actual_margin,
                                                                  dummy_margin)), 6),
            "margin_rmse": round(float(_rmse(actual_margin, margin_prediction)), 6),
            "dummy_margin_rmse": round(float(_rmse(actual_margin, dummy_margin)), 6),
        })
        for row, probability_value, margin_value in zip(test, probability, margin_prediction):
            predictions.append({
                "game_key": row["game_key"], "season": row["season"],
                "game_date": row["game_date"], "actual_win": int(row["target_win"]),
                "actual_margin": int(row["target_point_margin"]),
                "predicted_win_probability": round(float(probability_value), 8),
                "predicted_margin": round(float(margin_value), 8),
                "training_through": seasons[index - 1],
            })

    destination = Path(destination)
    prediction_fields = tuple(predictions[0])
    with (destination / "model_predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=prediction_fields)
        writer.writeheader()
        writer.writerows(predictions)
    report = {
        "format_version": 1, "evaluation": "expanding season window",
        "first_test_season": seasons[2], "last_test_season": seasons[-1],
        "numeric_features": list(NUMERIC), "categorical_features": list(CATEGORICAL),
        "classification": "logistic regression versus historical-prior dummy",
        "regression": "ridge regression versus historical-mean dummy",
        "folds": fold_metrics,
        "limitations": ["backtest only", "not causal", "not betting advice",
                        "game-only features omit roster and injury context"],
    }
    (destination / "model_metrics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
