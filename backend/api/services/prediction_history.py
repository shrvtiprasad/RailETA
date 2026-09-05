from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.database.database import get_connection


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "railway.db"
DEFAULT_METRICS_PATH = BACKEND_DIR / "ml" / "models" / "metrics.json"

SNAPSHOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS prediction_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number             TEXT NOT NULL,
    predicted_at             TEXT NOT NULL,
    station_code             TEXT,
    station_name             TEXT,
    predicted_eta            TEXT NOT NULL,
    predicted_delay_minutes  REAL,
    confidence               TEXT,
    current_delay_minutes    REAL,
    data_quality              TEXT,
    data_source              TEXT NOT NULL DEFAULT 'RailRadar + RailETA model'
);
CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_train_time
    ON prediction_snapshots(train_number, predicted_at);
"""


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, "", "—"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso_with_minutes(value: str | None, minutes: float) -> str | None:
    if value in (None, "", "—"):
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Timetable and live ETA timestamps are intentionally returned as local
    # railway time without a timezone. Preserve that shape for the operational
    # range so clients do not apply IST a second time to only the range fields.
    shifted = parsed + timedelta(minutes=minutes)
    return shifted.isoformat(timespec="seconds")


@lru_cache(maxsize=1)
def operational_error_minutes(metrics_path: Path = DEFAULT_METRICS_PATH) -> float | None:
    """Return the selected model's measured test MAE for an operational range."""

    if not metrics_path.exists():
        logger.warning("Model metrics unavailable for ETA range path=%s", metrics_path)
        return None
    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        selected = payload.get("selected_model", "railway_only")
        variant = payload.get(selected) or payload.get("railway_only")
        value = variant.get("test", {}).get("mae_minutes") if isinstance(variant, dict) else None
        number = float(value)
        return number if number >= 0 else None
    except (OSError, TypeError, ValueError, json.JSONDecodeError, AttributeError) as exc:
        logger.warning("Could not read measured ETA error path=%s error=%s", metrics_path, exc)
        return None


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SNAPSHOT_SCHEMA)
    connection.commit()


def _station(result: dict[str, Any]) -> dict[str, Any] | None:
    station = result.get("next_station")
    if isinstance(station, dict):
        return station
    stations = result.get("stations")
    if isinstance(stations, list) and stations and isinstance(stations[0], dict):
        return stations[0]
    return None


def _stability(rows: list[sqlite3.Row]) -> str:
    if len(rows) < 2:
        return "INSUFFICIENT_HISTORY"
    changes: list[float] = []
    for newer, older in zip(rows, rows[1:]):
        new_value = newer["predicted_delay_minutes"]
        old_value = older["predicted_delay_minutes"]
        if new_value is not None and old_value is not None:
            changes.append(abs(float(new_value) - float(old_value)))
    if not changes:
        return "INSUFFICIENT_HISTORY"
    largest_change = max(changes)
    if largest_change <= 2:
        return "STABLE"
    if largest_change <= 10:
        return "UPDATING"
    return "VOLATILE"


def record_prediction_snapshot(
    result: dict[str, Any],
    db_path: Path = DEFAULT_DB_PATH,
    metrics_path: Path = DEFAULT_METRICS_PATH,
) -> dict[str, Any] | None:
    """Persist a successful inference and return stable-ETA information.

    History storage is deliberately best-effort: a database write problem must
    not turn an otherwise valid live ETA into a fake or failed prediction.
    """

    station = _station(result)
    train_number = str(result.get("train_number") or "").strip()
    predicted_eta = station.get("predicted_arrival") if station else None
    if not train_number or not predicted_eta:
        logger.warning("Prediction snapshot skipped because required values are missing train=%s", train_number)
        return None

    predicted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    station_code = station.get("station_code")
    connection: sqlite3.Connection | None = None
    try:
        connection = get_connection(db_path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        previous = connection.execute(
            """
            SELECT * FROM prediction_snapshots
            WHERE train_number = ? AND station_code = ?
            ORDER BY predicted_at DESC, id DESC LIMIT 1
            """,
            (train_number, station_code),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO prediction_snapshots
                (train_number, predicted_at, station_code, station_name,
                 predicted_eta, predicted_delay_minutes, confidence,
                 current_delay_minutes, data_quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                train_number,
                predicted_at,
                station_code,
                station.get("station_name"),
                predicted_eta,
                station.get("predicted_delay_minutes"),
                station.get("confidence") or result.get("confidence"),
                result.get("current_delay_minutes"),
                station.get("data_quality") or result.get("data_quality"),
            ),
        )
        connection.commit()
        recent = connection.execute(
            """
            SELECT * FROM prediction_snapshots
            WHERE train_number = ? AND station_code = ?
            ORDER BY predicted_at DESC, id DESC LIMIT 5
            """,
            (train_number, station_code),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Prediction snapshot could not be stored train=%s error=%s", train_number, exc)
        return None
    finally:
        if connection is not None:
            connection.close()

    current_dt = _parse_datetime(predicted_eta)
    previous_eta = previous["predicted_eta"] if previous is not None else None
    previous_dt = _parse_datetime(previous_eta)
    change_minutes = round((current_dt - previous_dt).total_seconds() / 60, 2) if current_dt and previous_dt else None
    error_minutes = operational_error_minutes(metrics_path)
    stable_eta: dict[str, Any] = {
        "current_eta": predicted_eta,
        "previous_eta": previous_eta,
        "change_minutes": change_minutes,
        "stability": _stability(list(recent)),
        "reliability": station.get("confidence") or result.get("confidence"),
        "prediction_timestamp": predicted_at,
        "history_count_for_station": len(recent),
        "eta_range": None,
    }
    if error_minutes is not None:
        stable_eta["eta_range"] = {
            "lower": _iso_with_minutes(predicted_eta, -error_minutes),
            "upper": _iso_with_minutes(predicted_eta, error_minutes),
            "error_margin_minutes": round(error_minutes, 2),
            "basis": "selected model test MAE from backend/ml/models/metrics.json; operational, not calibrated probability",
        }
    return stable_eta


def stable_eta_from_history(
    train_number: str,
    current_result: dict[str, Any],
    db_path: Path = DEFAULT_DB_PATH,
    metrics_path: Path = DEFAULT_METRICS_PATH,
) -> dict[str, Any] | None:
    """Read stable-ETA history without creating a new snapshot."""

    station = _station(current_result)
    if not station:
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = get_connection(db_path)
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM prediction_snapshots
            WHERE train_number = ? AND station_code = ?
            ORDER BY predicted_at DESC, id DESC LIMIT 5
            """,
            (str(train_number).strip(), station.get("station_code")),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Prediction history lookup failed train=%s error=%s", train_number, exc)
        return None
    finally:
        if connection is not None:
            connection.close()
    current_eta = station.get("predicted_arrival")
    current_dt = _parse_datetime(current_eta)
    previous_eta = rows[0]["predicted_eta"] if rows else None
    previous_dt = _parse_datetime(previous_eta)
    error_minutes = operational_error_minutes(metrics_path)
    stable_eta: dict[str, Any] = {
        "current_eta": current_eta,
        "previous_eta": previous_eta,
        "change_minutes": round((current_dt - previous_dt).total_seconds() / 60, 2) if current_dt and previous_dt else None,
        "stability": _stability(list(rows)),
        "reliability": station.get("confidence") or current_result.get("confidence"),
        "prediction_timestamp": rows[0]["predicted_at"] if rows else None,
        "history_count_for_station": len(rows),
        "eta_range": None,
    }
    if error_minutes is not None:
        stable_eta["eta_range"] = {
            "lower": _iso_with_minutes(current_eta, -error_minutes),
            "upper": _iso_with_minutes(current_eta, error_minutes),
            "error_margin_minutes": round(error_minutes, 2),
            "basis": "selected model test MAE from backend/ml/models/metrics.json; operational, not calibrated probability",
        }
    return stable_eta
