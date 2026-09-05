from __future__ import annotations

import copy
import logging
import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from backend.ml.contract import DataUnavailableError
from backend.ml.features import WEATHER_FEATURES
from backend.ml.live_features import add_historical_aggregates, build_live_rows, current_coordinates
from backend.ml.predict import load_artifact
from .prediction_history import record_prediction_snapshot
from .railradar import RailRadarError, fetch_live_train
from .weather import current_weather


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = BACKEND_DIR / "ml" / "models" / "eta_pipeline.joblib"
DEFAULT_FEATURE_STORE = DEFAULT_MODEL_PATH.parent / "historical_feature_store.csv"
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "railway.db"
LIVE_REQUIRED_FIELDS = (
    "train_number",
    "current_station_code",
    "next_station_code",
    "scheduled_next_arrival",
    "scheduled_section_runtime_minutes",
)


def _value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", "--", "SRC"):
            return value
    return None


def _route_scalar(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("code", "stationCode", "station_code", "number", "value"):
            nested = value.get(key)
            if nested not in (None, "", "--", "SRC") and not isinstance(nested, (dict, list, tuple)):
                return str(nested).strip()
        return None
    if isinstance(value, (list, tuple)):
        return None
    return value


def _missing(value: Any) -> bool:
    if value in (None, "", "--", "SRC"):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def load_static_train_context(train_number: str, db_path: Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    """Load only existing timetable/station data; never invent coordinates or route stops."""

    if not db_path.exists():
        logger.warning("Static railway database is unavailable path=%s", db_path)
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(db_path))
        connection.row_factory = sqlite3.Row
        train = connection.execute(
            """
            SELECT train_number, train_name, train_type, source_station_code,
                   destination_station_code, distance_km, runs_days
            FROM trains WHERE train_number = ?
            """,
            (str(train_number).strip(),),
        ).fetchone()
        if train is None:
            return None
        stops = connection.execute(
            """
            SELECT ts.station_code, s.station_name, ts.sequence, ts.day_offset,
                   ts.arrival_time, ts.departure_time, ts.halt_minutes,
                   ts.distance_from_source, s.latitude, s.longitude
            FROM train_stops ts
            LEFT JOIN stations s ON s.station_code = ts.station_code
            WHERE ts.train_number = ?
            ORDER BY ts.sequence
            """,
            (str(train_number).strip(),),
        ).fetchall()
        route = []
        for stop in stops:
            row = dict(stop)
            route.append(
                {
                    "stationCode": row.get("station_code"),
                    "stationName": row.get("station_name"),
                    "sequence": row.get("sequence"),
                    "dayOffset": row.get("day_offset"),
                    "scheduledArrival": row.get("arrival_time"),
                    "scheduledDeparture": row.get("departure_time"),
                    "haltMinutes": row.get("halt_minutes"),
                    "distanceFromOrigin": row.get("distance_from_source"),
                    "lat": row.get("latitude"),
                    "lng": row.get("longitude"),
                    "isHalt": True,
                }
            )
        return {"train": dict(train), "route": route}
    except sqlite3.Error as exc:
        logger.warning("Static railway lookup failed train=%s error=%s", train_number, exc)
        return None
    finally:
        if connection is not None:
            connection.close()


def merge_static_context(live_payload: dict[str, Any], static_context: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing live fields from the local timetable while preserving live values."""

    if not isinstance(live_payload, dict):
        raise DataUnavailableError("RailRadar response must be a JSON object.")
    working = copy.deepcopy(live_payload)
    if "data" in working:
        if not isinstance(working["data"], dict):
            raise DataUnavailableError("RailRadar response contained a malformed data object.")
        data = working["data"]
    else:
        data = working
    if not static_context:
        return working

    static_train = static_context.get("train") if isinstance(static_context.get("train"), dict) else {}
    live_train = data.get("train") if isinstance(data.get("train"), dict) else {}
    live_train = {**static_train, **live_train}
    data["train"] = live_train
    data.setdefault("trainNumber", static_train.get("train_number"))
    data.setdefault("trainName", static_train.get("train_name"))
    data.setdefault("trainType", static_train.get("train_type"))
    data.setdefault("sourceStationCode", static_train.get("source_station_code"))
    data.setdefault("destinationStationCode", static_train.get("destination_station_code"))

    static_route = static_context.get("route") if isinstance(static_context.get("route"), list) else []
    live_route = data.get("route")
    if isinstance(live_route, dict):
        live_route = live_route.get("stops") or live_route.get("stations")
    if not isinstance(live_route, list):
        live_route = data.get("timeline")
    if not isinstance(live_route, list):
        live_route = []

    def route_key(stop: dict[str, Any]) -> tuple[Any, Any]:
        return (
            _route_scalar(_value(stop, "stationCode", "station_code", "code")),
            _route_scalar(_value(stop, "sequence", "seq")),
        )

    static_by_key = {route_key(stop): stop for stop in static_route if isinstance(stop, dict)}
    static_by_code = {
        _route_scalar(_value(stop, "stationCode", "station_code", "code")): stop
        for stop in static_route
        if isinstance(stop, dict) and _route_scalar(_value(stop, "stationCode", "station_code", "code"))
    }
    if live_route:
        enriched = []
        for stop in live_route:
            if not isinstance(stop, dict):
                continue
            match = static_by_key.get(route_key(stop)) or static_by_code.get(
                _value(stop, "stationCode", "station_code", "code")
            )
            enriched.append({**(match or {}), **stop})
        data["route"] = enriched
    elif static_route:
        data["route"] = static_route
    return working


def _current_state(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    data = payload.get("data", payload)
    location = data.get("currentLocation") if isinstance(data.get("currentLocation"), dict) else {}
    coordinates = current_coordinates(payload)
    state = _value(data, "status", "trainStatus", "currentStatus", "state") or _value(location, "status", "state")
    result: dict[str, Any] = {
        "station_code": _value(location, "stationCode", "station_code") or (rows[0].get("current_station_code") if rows else None),
        "sequence": _value(location, "sequence", "seq") or (rows[0].get("station_sequence") if rows else None),
        "state": state or "unknown",
    }
    if coordinates is not None:
        result.update({"latitude": coordinates[0], "longitude": coordinates[1]})
    return result


def _add_delay(timestamp: Any, minutes: float) -> str | None:
    if _missing(timestamp):
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return str(timestamp)
    return (parsed + timedelta(minutes=float(minutes))).isoformat(timespec="seconds")


def _baseline_delay(row: dict[str, Any]) -> float:
    for column in ("current_departure_delay_minutes", "current_arrival_delay_minutes"):
        value = row.get(column)
        if not _missing(value):
            try:
                number = float(value)
                if math.isfinite(number):
                    return number
            except (TypeError, ValueError):
                pass
    return 0.0


def _weather_model_features(artifact: dict[str, Any]) -> list[str]:
    names = [name for name in artifact.get("numeric_features", []) if name in WEATHER_FEATURES]
    if artifact.get("weather_included") and not names:
        return list(WEATHER_FEATURES)
    return names


def _model_predictions(
    rows: list[dict[str, Any]],
    artifact: dict[str, Any],
    weather: dict[str, Any] | None,
) -> tuple[list[float] | None, list[str], str | None]:
    feature_columns = [*artifact.get("categorical_features", []), *artifact.get("numeric_features", [])]
    if not feature_columns:
        return None, [], "trained model artifact has no feature schema"
    missing_live = set()
    for row in rows:
        missing_live.update(column for column in LIVE_REQUIRED_FIELDS if _missing(row.get(column)))
    weather_features = _weather_model_features(artifact)
    if weather_features:
        for column in weather_features:
            if weather is None or _missing(weather.get(column)):
                missing_live.add(column)
    if missing_live:
        return None, sorted(missing_live), "required live features are missing"

    frame = pd.DataFrame(rows)
    missing_schema = [column for column in feature_columns if column not in frame.columns]
    if missing_schema:
        return None, missing_schema, "trained model schema could not be constructed"
    try:
        # The trained target is the arrival delay for the next station. Feed
        # each predicted section delay into the following section so the
        # downstream route is a real roll-forward forecast rather than N
        # independent predictions all using the original live delay.
        sequential_rows = [dict(row) for row in rows]
        predictions: list[float] = []
        for index, row in enumerate(sequential_rows):
            current_frame = pd.DataFrame([row])
            raw = artifact["pipeline"].predict(current_frame[feature_columns])
            if len(raw) != 1:
                return None, [], "model returned an invalid section prediction"
            prediction = float(raw[0])
            if not math.isfinite(prediction):
                return None, [], "model returned invalid prediction values"
            predictions.append(prediction)
            if index + 1 < len(sequential_rows):
                sequential_rows[index + 1]["current_arrival_delay_minutes"] = prediction
                sequential_rows[index + 1]["current_departure_delay_minutes"] = prediction
        return predictions, [], None
    except Exception as exc:  # model/preprocessor errors must become explicit baseline fallbacks
        return None, [], f"model inference failed: {exc}"


def predict_live_eta(
    live_payload: dict[str, Any],
    weather: dict[str, Any] | None,
    model_path: Path = DEFAULT_MODEL_PATH,
    feature_store: Path = DEFAULT_FEATURE_STORE,
    static_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate live ETA predictions from RailRadar/Open-Meteo and the saved model."""

    enriched_payload = merge_static_context(live_payload, static_context)
    rows = build_live_rows(enriched_payload, weather)
    if not rows:
        raise DataUnavailableError("RailRadar returned no upcoming station for ETA prediction.")
    rows = add_historical_aggregates(rows, feature_store)

    artifact: dict[str, Any] | None = None
    fallback_reason: str | None = None
    missing_live_features: list[str] = []
    try:
        artifact = load_artifact(model_path)
    except (DataUnavailableError, OSError, ValueError) as exc:
        fallback_reason = f"trained model unavailable: {exc}"
        logger.warning("ETA fallback used because model could not be loaded path=%s error=%s", model_path, exc)

    predictions: list[float] | None = None
    if artifact is not None:
        predictions, missing_live_features, model_error = _model_predictions(rows, artifact, weather)
        if model_error:
            fallback_reason = model_error
            logger.warning(
                "ETA fallback used train=%s reason=%s missing_live_features=%s",
                rows[0].get("train_number"),
                model_error,
                missing_live_features,
            )

    use_model = predictions is not None
    if not use_model:
        predictions = [_baseline_delay(row) for row in rows]
        if missing_live_features:
            logger.warning(
                "ETA missing live features train=%s features=%s",
                rows[0].get("train_number"),
                missing_live_features,
            )

    stations = []
    for row, predicted_delay in zip(rows, predictions):
        predicted_delay = round(float(predicted_delay), 2)
        section_current_delay = (
            stations[-1]["predicted_delay_minutes"]
            if stations
            else _baseline_delay(row)
        )
        weather_context_available = weather is not None and any(
            not _missing(weather.get(column)) for column in WEATHER_FEATURES
        )
        confidence = (
            "HIGH"
            if use_model and not missing_live_features and weather_context_available
            else "MEDIUM"
            if use_model
            else "LOW"
        )
        stations.append(
            {
                "station_code": row.get("next_station_code"),
                "station_name": row.get("next_station_name"),
                "sequence": row.get("next_station_sequence"),
                "scheduled_arrival": row.get("scheduled_next_arrival"),
                "scheduled_departure": row.get("scheduled_next_departure"),
                "predicted_departure": _add_delay(row.get("scheduled_next_departure"), predicted_delay),
                "predicted_arrival": _add_delay(row.get("scheduled_next_arrival"), predicted_delay),
                "current_delay_minutes": _baseline_delay(row),
                "section_current_delay_minutes": round(section_current_delay, 2),
                "predicted_additional_delay_minutes": round(predicted_delay - section_current_delay, 2),
                "predicted_delay_minutes": predicted_delay,
                "prediction_source": "model" if use_model else "baseline",
                "confidence": confidence,
                "data_quality": confidence,
                "prediction_horizon": "next_station",
                "weather_context": weather,
                "important_contributing_factors": ["current RailRadar delay", "scheduled section and train features"],
            }
        )

    current_state = _current_state(enriched_payload, rows)
    data = enriched_payload.get("data", enriched_payload)
    train_number = str(_value(data, "trainNumber", "trainNo") or rows[0].get("train_number") or "")
    result: dict[str, Any] = {
        "train_number": train_number,
        "model_version": artifact.get("model_version", "unavailable") if artifact else "unavailable",
        "railway_data_status": "live_railradar",
        "current_position": current_state,
        "current_delay_minutes": stations[0]["current_delay_minutes"],
        "prediction_source": "model" if use_model else "baseline",
        "confidence": stations[0]["confidence"],
        "data_quality": stations[0]["data_quality"],
        "missing_live_features": missing_live_features,
        "fallback_reason": fallback_reason,
        "stations": stations,
        "next_station": stations[0],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    logger.info(
        "ETA prediction generated train=%s stations=%d source=%s",
        train_number,
        len(stations),
        result["prediction_source"],
    )
    return result


async def generate_live_eta(train_number: str) -> dict[str, Any]:
    """Fetch live sources, run the existing model, and persist one snapshot."""

    try:
        live_payload = await fetch_live_train(train_number)
    except RailRadarError:
        raise

    static_context = load_static_train_context(train_number)
    enriched_payload = merge_static_context(live_payload, static_context)
    coordinates = current_coordinates(enriched_payload)
    weather = None
    weather_status = "unavailable_missing_coordinates"
    if coordinates is not None:
        try:
            weather = await current_weather(float(coordinates[0]), float(coordinates[1]))
            weather_status = "live_open_meteo_current"
        except RuntimeError as exc:
            logger.warning("Open-Meteo failure train=%s error=%s", train_number, exc)
            weather_status = "unavailable_provider_error"

    result = predict_live_eta(enriched_payload, weather)
    result["weather_data_status"] = weather_status
    result["weather_source"] = "Open-Meteo Forecast API" if weather is not None else None
    stable_eta = record_prediction_snapshot(result)
    if stable_eta is not None:
        result["stable_eta"] = stable_eta
    return result
