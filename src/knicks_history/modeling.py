"""Chronological, inspectable baselines for private Knicks research."""
import csv
import hashlib
import json
import math
from pathlib import Path

TRAIN_SEASONS = ("2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23")
VALIDATION_SEASONS = ("2023-24",)
TEST_SEASONS = ("2024-25", "2025-26")
NUMERIC_FEATURES = (
    "games_played_before", "season_to_date_win_pct", "prior_5_pts",
    "prior_5_opponent_pts", "prior_5_point_margin", "prior_5_reb",
    "prior_5_ast", "prior_5_tov", "prior_5_fg_pct", "prior_5_fg3_pct",
    "prior_5_ft_pct",
)
CATEGORICAL_FEATURES = ("opponent_abbrev", "venue_side")


def chronological_split(rows):
    accepted = set(TRAIN_SEASONS + VALIDATION_SEASONS + TEST_SEASONS)
    unknown = sorted({row["season"] for row in rows} - accepted)
    if unknown:
        raise ValueError(f"Unrecognized modeling seasons: {', '.join(unknown)}")
    complete = [dict(row) for row in rows if int(row["history_games"]) == 5]
    groups = {
        "train": [row for row in complete if row["season"] in TRAIN_SEASONS],
        "validation": [row for row in complete if row["season"] in VALIDATION_SEASONS],
        "test": [row for row in complete if row["season"] in TEST_SEASONS],
    }
    if any(not values for values in groups.values()):
        raise ValueError("Training, validation, and test partitions must all be non-empty")
    return groups


def _xy(rows, target):
    features = [{name: row.get(name) for name in NUMERIC_FEATURES + CATEGORICAL_FEATURES}
                for row in rows]
    return features, [row[target] for row in rows]


def _rmse(actual, predicted):
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))


def _bootstrap(actual, predicted, metric, seed=52, samples=400):
    import numpy as np
    rng = np.random.default_rng(seed)
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    scores = []
    for _ in range(samples):
        positions = rng.integers(0, len(actual), len(actual))
        try:
            scores.append(float(metric(actual[positions], predicted[positions])))
        except ValueError:
            continue
    if not scores:
        return None
    return {"low": round(float(np.quantile(scores, .025)), 6),
            "high": round(float(np.quantile(scores, .975)), 6)}


def _write_model_card(path, run_id, metrics):
    path.write_text(f"""# NYK pregame baseline model

Run: `{run_id}`

This private research artifact compares an interpretable logistic-regression win
probability model and Ridge point-margin model against dummy baselines. Inputs contain
only information available before each game and require five completed prior games.

- Training: 2017-18 through 2022-23
- Validation: 2023-24
- Held-out test: 2024-25 and 2025-26
- Win log loss: {metrics['classification']['log_loss']}
- Margin MAE: {metrics['regression']['mae']}

The results are backtests, not causal estimates, betting advice, or guarantees about
future games. Small samples, roster changes, injuries, schedule strength, and unmodeled
context limit interpretation.
""", encoding="utf-8")


def train_models(rows, output):
    try:
        import joblib
        import numpy as np
        import pandas as pd
        import polars as pl
        from sklearn.compose import ColumnTransformer
        from sklearn.dummy import DummyClassifier, DummyRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression, Ridge
        from sklearn.metrics import (accuracy_score, brier_score_loss, log_loss,
                                     mean_absolute_error, r2_score, roc_auc_score)
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
    except ImportError as exc:
        raise RuntimeError("Install the ml extra to train models") from exc
    output = Path(output)
    if output.exists():
        raise FileExistsError("Use an empty model output directory")
    output.mkdir(parents=True)
    groups = chronological_split(rows)
    source_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    run_id = "model-" + source_hash[:12]

    def preprocessor():
        numeric = Pipeline([("impute", SimpleImputer(strategy="median")),
                            ("scale", StandardScaler())])
        categorical = Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                                ("encode", OneHotEncoder(handle_unknown="ignore"))])
        return ColumnTransformer([("numeric", numeric, list(NUMERIC_FEATURES)),
                                  ("categorical", categorical, list(CATEGORICAL_FEATURES))])

    x_train, y_train_win = _xy(groups["train"], "target_win")
    x_validation, y_validation_win = _xy(groups["validation"], "target_win")
    x_test, y_test_win = _xy(groups["test"], "target_win")
    x_train, x_validation, x_test = map(pd.DataFrame, (x_train, x_validation, x_test))
    classifier_candidates = []
    for value in (.1, 1.0, 10.0):
        model = Pipeline([("features", preprocessor()),
                          ("model", LogisticRegression(C=value, max_iter=2000, random_state=52))])
        model.fit(x_train, y_train_win)
        score = log_loss(y_validation_win, model.predict_proba(x_validation)[:, 1], labels=[0, 1])
        classifier_candidates.append((score, value, model))
    _, selected_c, classifier = min(classifier_candidates, key=lambda item: (item[0], item[1]))
    classifier.fit(pd.concat((x_train, x_validation), ignore_index=True),
                   y_train_win + y_validation_win)
    win_probability = classifier.predict_proba(x_test)[:, 1]
    win_prediction = (win_probability >= .5).astype(int)
    dummy_classifier = DummyClassifier(strategy="prior").fit(
        pd.concat((x_train, x_validation), ignore_index=True),
        y_train_win + y_validation_win)
    dummy_probability = dummy_classifier.predict_proba(x_test)[:, 1]

    x_train_margin, y_train_margin = _xy(groups["train"], "target_point_margin")
    x_validation_margin, y_validation_margin = _xy(groups["validation"], "target_point_margin")
    x_test_margin, y_test_margin = _xy(groups["test"], "target_point_margin")
    x_train_margin, x_validation_margin, x_test_margin = map(
        pd.DataFrame, (x_train_margin, x_validation_margin, x_test_margin))
    regressor_candidates = []
    for value in (.1, 1.0, 10.0, 100.0):
        model = Pipeline([("features", preprocessor()), ("model", Ridge(alpha=value))])
        model.fit(x_train_margin, y_train_margin)
        score = mean_absolute_error(y_validation_margin, model.predict(x_validation_margin))
        regressor_candidates.append((score, value, model))
    _, selected_alpha, regressor = min(regressor_candidates, key=lambda item: (item[0], item[1]))
    regressor.fit(pd.concat((x_train_margin, x_validation_margin), ignore_index=True),
                  y_train_margin + y_validation_margin)
    margin_prediction = regressor.predict(x_test_margin)
    dummy_regressor = DummyRegressor(strategy="median").fit(
        pd.concat((x_train_margin, x_validation_margin), ignore_index=True),
        y_train_margin + y_validation_margin)
    dummy_margin = dummy_regressor.predict(x_test_margin)

    classification = {
        "selected_c": selected_c,
        "accuracy": round(float(accuracy_score(y_test_win, win_prediction)), 6),
        "roc_auc": round(float(roc_auc_score(y_test_win, win_probability)), 6),
        "log_loss": round(float(log_loss(y_test_win, win_probability, labels=[0, 1])), 6),
        "brier": round(float(brier_score_loss(y_test_win, win_probability)), 6),
        "dummy_log_loss": round(float(log_loss(y_test_win, dummy_probability, labels=[0, 1])), 6),
        "log_loss_ci95": _bootstrap(y_test_win, win_probability,
                                     lambda a, p: log_loss(a, p, labels=[0, 1])),
    }
    regression = {
        "selected_alpha": selected_alpha,
        "mae": round(float(mean_absolute_error(y_test_margin, margin_prediction)), 6),
        "rmse": round(float(_rmse(y_test_margin, margin_prediction)), 6),
        "r2": round(float(r2_score(y_test_margin, margin_prediction)), 6),
        "dummy_mae": round(float(mean_absolute_error(y_test_margin, dummy_margin)), 6),
        "mae_ci95": _bootstrap(y_test_margin, margin_prediction,
                                lambda a, p: mean_absolute_error(a, p)),
    }
    metrics = {"classification": classification, "regression": regression,
               "rows": {name: len(values) for name, values in groups.items()}}
    predictions = []
    for row, probability, margin in zip(groups["test"], win_probability, margin_prediction):
        predictions.append({"season": row["season"], "game_id": str(row["game_id"]),
                            "game_date": row["game_date"], "split": "test",
                            "actual_win": int(row["target_win"]),
                            "actual_margin": int(row["target_point_margin"]),
                            "predicted_win_probability": round(float(probability), 8),
                            "predicted_margin": round(float(margin), 8)})
    feature_names = classifier.named_steps["features"].get_feature_names_out()
    coefficients = [{"model": "win_probability", "feature": str(name),
                     "coefficient": float(value)}
                    for name, value in zip(feature_names,
                                           classifier.named_steps["model"].coef_[0])]
    margin_names = regressor.named_steps["features"].get_feature_names_out()
    coefficients += [{"model": "point_margin", "feature": str(name),
                      "coefficient": float(value)}
                     for name, value in zip(margin_names, regressor.named_steps["model"].coef_)]
    pl.DataFrame(predictions).write_parquet(output / "predictions.parquet", compression="zstd")
    pl.DataFrame(coefficients).write_parquet(output / "coefficients.parquet", compression="zstd")
    joblib.dump(classifier, output / "win-probability.joblib")
    joblib.dump(regressor, output / "point-margin.joblib")
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    run = {"format_version": 1, "run_id": run_id, "source_sha256": source_hash,
           "train_seasons": list(TRAIN_SEASONS), "validation_seasons": list(VALIDATION_SEASONS),
           "test_seasons": list(TEST_SEASONS), "numeric_features": list(NUMERIC_FEATURES),
           "categorical_features": list(CATEGORICAL_FEATURES), "random_seed": 52,
           "limitations": ["backtest only", "not causal", "not betting advice"]}
    (output / "model-run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    _write_model_card(output / "MODEL_CARD.md", run_id, metrics)
    return {"run": run, "metrics": metrics}
