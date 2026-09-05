from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .contract import DataUnavailableError, require_file


TARGET_COLUMN = "next_station_arrival_delay_minutes"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = PROJECT_ROOT / "backend" / "data" / "processed" / "running_events.csv"
DEFAULT_TRAINS = PROJECT_ROOT / "backend" / "data" / "processed" / "trains.csv"
DEFAULT_STOPS = PROJECT_ROOT / "backend" / "data" / "processed" / "stops.csv"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "backend" / "ml" / "models"
DEFAULT_OUTPUT = DEFAULT_MODEL_DIR / "eta_pipeline.joblib"


def _dependencies():
    try:
        import joblib
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise DataUnavailableError(
            "ML dependencies are not installed. Install backend/requirements.txt before training."
        ) from exc
    return joblib, ColumnTransformer, SimpleImputer, mean_absolute_error, mean_squared_error, median_absolute_error, Pipeline, OneHotEncoder, XGBRegressor


def chronological_split(frame, train_fraction: float = 0.70, validation_fraction: float = 0.15):
    dates = sorted(frame["journey_date"].dropna().unique())
    if len(dates) < 3:
        raise DataUnavailableError("At least three distinct journey dates are required; random row splitting is disabled.")
    train_end = max(1, int(len(dates) * train_fraction))
    validation_end = max(train_end + 1, int(len(dates) * (train_fraction + validation_fraction)))
    validation_end = min(validation_end, len(dates) - 1)
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:validation_end])
    test_dates = set(dates[validation_end:])
    return (
        frame[frame["journey_date"].isin(train_dates)].copy(),
        frame[frame["journey_date"].isin(validation_dates)].copy(),
        frame[frame["journey_date"].isin(test_dates)].copy(),
    )


def _build_pipeline(categorical: list[str], numeric: list[str], model_params: dict[str, Any] | None = None):
    _, ColumnTransformer, SimpleImputer, *_rest, Pipeline, OneHotEncoder, XGBRegressor = _dependencies()
    try:
        encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=2, sparse_output=False)
    except TypeError:  # scikit-learn < 1.2 compatibility
        encoder = OneHotEncoder(handle_unknown="ignore", min_frequency=2, sparse=False)
    preprocess = ColumnTransformer(
        transformers=[
            ("categorical", Pipeline([("imputer", SimpleImputer(strategy="most_frequent")), ("onehot", encoder)]), categorical),
            ("numeric", SimpleImputer(strategy="median", add_indicator=True), numeric),
        ],
        remainder="drop",
    )
    params = {
        "objective": "reg:squarederror",
        "n_estimators": 450,
        "max_depth": 6,
        "learning_rate": 0.05,
        "min_child_weight": 3,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "gamma": 0.0,
        "reg_alpha": 0.05,
        "reg_lambda": 1.0,
        "random_state": 42,
        "n_jobs": 1,
        "tree_method": "hist",
    }
    params.update(model_params or {})
    return Pipeline([("preprocess", preprocess), ("model", XGBRegressor(**params))])


def metrics(y_true, predictions, baseline) -> dict[str, Any]:
    _, _, _, mean_absolute_error, mean_squared_error, median_absolute_error, *_ = _dependencies()
    errors = np.asarray(predictions) - np.asarray(y_true)
    absolute = np.abs(errors)
    baseline_mae = float(mean_absolute_error(y_true, baseline))
    model_mae = float(mean_absolute_error(y_true, predictions))
    return {
        "rows": int(len(y_true)),
        "mae_minutes": round(model_mae, 4),
        "rmse_minutes": round(math.sqrt(float(mean_squared_error(y_true, predictions))), 4),
        "median_absolute_error_minutes": round(float(median_absolute_error(y_true, predictions)), 4),
        "within_5_minutes": round(float(np.mean(absolute <= 5)), 4),
        "within_10_minutes": round(float(np.mean(absolute <= 10)), 4),
        "baseline_mae_minutes": round(baseline_mae, 4),
        "mae_improvement_minutes": round(baseline_mae - model_mae, 4),
        "mae_improvement_percent": round(((baseline_mae - model_mae) / baseline_mae) * 100, 4) if baseline_mae else None,
    }


def _fit_variant(frame, train, validation, test, categorical, numeric, candidates):
    best_pipeline = None
    best_params = None
    best_validation = None
    for candidate in candidates:
        pipeline = _build_pipeline(categorical, numeric, candidate)
        pipeline.fit(train[categorical + numeric], train[TARGET_COLUMN])
        predictions = pipeline.predict(validation[categorical + numeric])
        validation_result = metrics(
            validation[TARGET_COLUMN],
            predictions,
            validation["current_departure_delay_minutes"].fillna(validation["current_arrival_delay_minutes"]).fillna(0),
        )
        if best_validation is None or validation_result["mae_minutes"] < best_validation["mae_minutes"]:
            best_pipeline, best_params, best_validation = pipeline, candidate, validation_result

    train_validation = pd_concat([train, validation])
    final_pipeline = _build_pipeline(categorical, numeric, best_params)
    final_pipeline.fit(train_validation[categorical + numeric], train_validation[TARGET_COLUMN])
    test_predictions = final_pipeline.predict(test[categorical + numeric])
    test_result = metrics(
        test[TARGET_COLUMN],
        test_predictions,
        test["current_departure_delay_minutes"].fillna(test["current_arrival_delay_minutes"]).fillna(0),
    )
    return {
        "pipeline": final_pipeline,
        "categorical_features": categorical,
        "numeric_features": numeric,
        "best_params": best_params,
        "validation_metrics": best_validation,
        "test_metrics": test_result,
    }


def pd_concat(frames):
    try:
        import pandas as pd
        return pd.concat(frames, ignore_index=True)
    except ImportError as exc:
        raise DataUnavailableError("pandas is required to train the model.") from exc


def _feature_importance(pipeline) -> list[dict[str, Any]]:
    try:
        names = pipeline.named_steps["preprocess"].get_feature_names_out()
        values = pipeline.named_steps["model"].feature_importances_
        pairs = zip(names, values)
        return [
            {"feature": str(name), "importance": round(float(value), 8)}
            for name, value in sorted(pairs, key=lambda pair: pair[1], reverse=True)
        ]
    except (AttributeError, KeyError):
        return []


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def train_model(
    events_path: Path = DEFAULT_EVENTS,
    trains_path: Path = DEFAULT_TRAINS,
    stops_path: Path = DEFAULT_STOPS,
    output_path: Path = DEFAULT_OUTPUT,
    min_rows: int = 100,
) -> dict[str, Any]:
    try:
        from .features import WEATHER_FEATURES, load_training_frame, model_features
    except ImportError as exc:
        raise DataUnavailableError(
            "ML dependencies are not installed. Install backend/requirements.txt before training."
        ) from exc
    require_file(events_path, "event-level historical running data")
    frame = load_training_frame(events_path, trains_path, stops_path).dropna(subset=[TARGET_COLUMN]).copy()
    if len(frame) < min_rows:
        raise DataUnavailableError(f"Only {len(frame)} usable real section rows are available; at least {min_rows} are required.")
    train, validation, test = chronological_split(frame)
    if train.empty or validation.empty or test.empty:
        raise DataUnavailableError("Chronological split produced an empty partition; more real journey dates are required.")

    railway_categorical, railway_numeric = model_features(frame, include_weather=False)
    weather_categorical, weather_numeric = model_features(frame, include_weather=True)
    candidates = [
        {},
        {"max_depth": 4, "learning_rate": 0.04, "min_child_weight": 5},
        {"max_depth": 8, "learning_rate": 0.03, "min_child_weight": 2},
    ]
    railway = _fit_variant(frame, train, validation, test, railway_categorical, railway_numeric, candidates)
    weather_available = frame[[column for column in WEATHER_FEATURES if column in frame.columns]].notna().any().any()
    weather = None
    if weather_available:
        weather = _fit_variant(frame, train, validation, test, weather_categorical, weather_numeric, candidates)
    selected_name = (
        "weather_aware"
        if weather is not None and weather["validation_metrics"]["mae_minutes"] < railway["validation_metrics"]["mae_minutes"]
        else "railway_only"
    )
    selected = weather if selected_name == "weather_aware" else railway

    joblib, *_ = _dependencies()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "model_version": "eta-xgboost-v2-section-weather-ablation",
        "model_type": "XGBRegressor",
        "target": TARGET_COLUMN,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": selected["pipeline"],
        "categorical_features": selected["categorical_features"],
        "numeric_features": selected["numeric_features"],
        "weather_included": selected_name == "weather_aware",
        "data_source": "RailKit Train History API",
        "weather_source": "Open-Meteo Historical Weather API",
        "best_params": selected["best_params"],
    }
    joblib.dump(artifacts, output_path)
    joblib.dump(railway, output_dir / "eta_railway_only.joblib")
    if weather is not None:
        joblib.dump(weather, output_dir / "eta_weather_aware.joblib")

    date_ranges = {
        "train": [min(train["journey_date"]), max(train["journey_date"])],
        "validation": [min(validation["journey_date"]), max(validation["journey_date"])],
        "test": [min(test["journey_date"]), max(test["journey_date"])],
    }
    metrics_report = {
        "baseline": {"validation": railway["validation_metrics"], "test": railway["test_metrics"]},
        "railway_only": {"validation": railway["validation_metrics"], "test": railway["test_metrics"]},
        "weather_aware": (
            {"validation": weather["validation_metrics"], "test": weather["test_metrics"]}
            if weather is not None
            else {"status": "not_trained", "reason": "No historical weather observations were matched to the event data."}
        ),
        "selected_model": selected_name,
    }
    feature_schema = {
        "target": TARGET_COLUMN,
        "categorical_features": selected["categorical_features"],
        "numeric_features": selected["numeric_features"],
        "weather_features": [name for name in selected["numeric_features"] if name in __import__("backend.ml.features", fromlist=["WEATHER_FEATURES"]).WEATHER_FEATURES],
    }
    metadata = {
        "model_version": artifacts["model_version"],
        "model_type": artifacts["model_type"],
        "target": TARGET_COLUMN,
        "trained_at": artifacts["created_at"],
        "historical_railway_source": artifacts["data_source"],
        "historical_weather_source": artifacts["weather_source"],
        "historical_date_range": [min(frame["journey_date"]), max(frame["journey_date"])],
        "ml_section_row_count": int(len(frame)),
        "unique_trains": int(frame["train_number"].nunique()),
        "unique_stations": int(pd_unique(frame, ["current_station_code", "next_station_code"])),
        "unique_sections": int(frame["section_id"].nunique()),
        "train_date_ranges": date_ranges,
        "railway_features": railway_categorical + railway_numeric,
        "weather_features": [name for name in WEATHER_FEATURES if name in frame.columns],
        "selected_model": selected_name,
        "best_params": selected["best_params"],
    }
    _write_json(output_dir / "feature_schema.json", feature_schema)
    _write_json(output_dir / "model_metadata.json", metadata)
    _write_json(output_dir / "metrics.json", metrics_report)
    _write_json(output_dir / "feature_importance.json", {"selected_model": selected_name, "features": _feature_importance(selected["pipeline"])})
    try:
        frame.to_csv(output_dir / "historical_feature_store.csv", index=False)
    except OSError as exc:
        raise DataUnavailableError(f"Could not save the historical feature store: {exc}") from exc
    report = {"model_path": str(output_path), **metrics_report, "date_ranges": date_ranges}
    print(json.dumps(report, indent=2, default=str))
    return report


def pd_unique(frame, columns):
    values = []
    for column in columns:
        values.extend(frame[column].dropna().astype(str).tolist())
    return len(set(values))


def main() -> int:
    parser = argparse.ArgumentParser(description="Train RailETA's real-data-only section-level XGBoost models.")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--trains", type=Path, default=DEFAULT_TRAINS)
    parser.add_argument("--stops", type=Path, default=DEFAULT_STOPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-rows", type=int, default=100)
    args = parser.parse_args()
    try:
        train_model(args.events, args.trains, args.stops, args.output, args.min_rows)
    except DataUnavailableError as exc:
        print(str(exc))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
