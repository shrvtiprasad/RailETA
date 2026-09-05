from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.services.railradar import RailRadarError, fetch_live_train
from backend.api.services.weather import current_weather
from backend.ml.contract import DataUnavailableError
from backend.ml.live_features import add_historical_aggregates, build_live_rows, current_coordinates


router = APIRouter(prefix="/trains", tags=["ETA Prediction"])
MODEL_PATH = Path(__file__).resolve().parents[2] / "ml" / "models" / "eta_pipeline.joblib"


def _add_delay(timestamp: str | None, minutes: float) -> str | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    return (parsed + timedelta(minutes=float(minutes))).isoformat(timespec="seconds")


@router.get("/{train_number}/eta")
async def predict_train_eta(train_number: str):
    try:
        live_payload = await fetch_live_train(train_number)
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    data = live_payload.get("data", live_payload) if isinstance(live_payload, dict) else {}
    current_location = data.get("currentLocation") if isinstance(data, dict) and isinstance(data.get("currentLocation"), dict) else {}
    coordinates = current_coordinates(live_payload)
    weather = None
    weather_status = "unavailable_missing_coordinates"
    if coordinates is not None:
        try:
            weather = await current_weather(float(coordinates[0]), float(coordinates[1]))
            weather_status = "live_open_meteo_current"
        except RuntimeError:
            weather_status = "unavailable_provider_error"

    try:
        import pandas as pd
        from backend.ml.predict import load_artifact

        artifact = load_artifact(MODEL_PATH)
        rows = build_live_rows(live_payload, weather)
        rows = add_historical_aggregates(rows, MODEL_PATH.parent / "historical_feature_store.csv")
        if not rows:
            raise DataUnavailableError("RailRadar returned no upcoming halts for prediction.")
        feature_columns = artifact["categorical_features"] + artifact["numeric_features"]
        frame = pd.DataFrame(rows)
        for column in feature_columns:
            if column not in frame.columns:
                frame[column] = None
        predictions = artifact["pipeline"].predict(frame[feature_columns])
    except (ImportError, DataUnavailableError, OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"ETA model is unavailable: {exc}") from exc

    stations = []
    for row, prediction in zip(rows, predictions):
        predicted_delay = round(float(prediction), 2)
        missing_history = sum(row.get(column) is None for column in (
            "historical_train_delay_mean",
            "historical_train_station_delay_mean",
            "historical_station_delay_mean",
            "historical_section_runtime_mean",
        ))
        reliability = "HIGH" if weather is not None and missing_history == 0 else "MEDIUM" if weather is not None else "LOW"
        stations.append({
            "station_code": row.get("next_station_code"),
            "station_name": row.get("next_station_name"),
            "scheduled_arrival": row.get("scheduled_next_arrival"),
            "predicted_arrival": _add_delay(row.get("scheduled_next_arrival"), predicted_delay),
            "current_delay_minutes": row.get("current_departure_delay_minutes"),
            "predicted_delay_minutes": predicted_delay,
            "confidence": reliability,
            "prediction_horizon": "next_station",
            "weather_context": weather,
            "important_contributing_factors": ["current RailRadar delay", "section and train history features"],
        })
    return {
        "train_number": train_number,
        "model_version": artifact.get("model_version", "unknown"),
        "railway_data_status": "live_railradar",
        "weather_data_status": weather_status,
        "stations": stations,
    }
