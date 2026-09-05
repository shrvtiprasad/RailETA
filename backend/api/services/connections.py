from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment,misc]

from .eta import load_static_train_context


IST = ZoneInfo("Asia/Kolkata") if ZoneInfo is not None else None
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "railway.db"
DEFAULT_TRANSFER_MINUTES = 10
DEFAULT_MEDIUM_MARGIN_MINUTES = 20
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "MISSED": 3}


def _station_code(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("stationCode") or value.get("station_code") or value.get("code")
    if value in (None, "", "—"):
        return None
    return str(value).strip()


def _schedule_datetime(value: Any, reference: date, day_offset: Any = 0) -> datetime | None:
    """Parse a schedule as an IST-aware datetime, including day offsets."""

    if value in (None, "", "—"):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None and IST is not None:
            parsed = parsed.replace(tzinfo=IST)
        if parsed.tzinfo is not None and IST is not None:
            parsed = parsed.astimezone(IST)
        return parsed
    except ValueError:
        pass
    try:
        parts = text.split(":")
        parsed_time = time(int(parts[0]), int(parts[1]))
        offset = int(float(day_offset or 0))
        if IST is not None:
            return datetime.combine(reference + timedelta(days=offset), parsed_time, tzinfo=IST)
        return datetime.combine(reference + timedelta(days=offset), parsed_time)
    except (TypeError, ValueError, IndexError):
        return None


def _route(context: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in context.get("route", []) if isinstance(item, dict)]


def _configured_minutes(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _minimum_transfer_minutes(station_code: str | None) -> int:
    """Use a station override when configured, otherwise the documented default."""

    default = _configured_minutes(
        "RAILETA_DEFAULT_MINIMUM_TRANSFER_MINUTES",
        DEFAULT_TRANSFER_MINUTES,
    )
    raw_overrides = os.getenv("RAILETA_STATION_TRANSFER_MINUTES_JSON", "").strip()
    if not raw_overrides or not station_code:
        return default
    try:
        overrides = json.loads(raw_overrides)
    except json.JSONDecodeError:
        return default
    if not isinstance(overrides, dict):
        return default
    try:
        return max(0, int(overrides.get(station_code, default)))
    except (TypeError, ValueError):
        return default


def _risk_for_margin(available_minutes: float, margin_minutes: float) -> tuple[str, str]:
    medium_margin = _configured_minutes(
        "RAILETA_CONNECTION_MEDIUM_MARGIN_MINUTES",
        DEFAULT_MEDIUM_MARGIN_MINUTES,
    )
    if available_minutes <= 0:
        return "MISSED", "The connecting train is scheduled before the predicted arrival. Choose a later real service if available."
    if margin_minutes < 0:
        return "HIGH", "Connection buffer is below the required transfer time; choose a later real service if available."
    if margin_minutes < medium_margin:
        return "MEDIUM", "Connection is possible but tight; monitor the live ETA."
    return "LOW", "Connection has a sufficient scheduled transfer buffer."


def _running_weekdays(runs_days: Any) -> set[int] | None:
    """Convert the timetable's origin running-day text to weekday numbers."""

    text = str(runs_days or "").strip().lower()
    if not text:
        return None
    if "daily" in text:
        return set(range(7))
    names = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
    result = {number for name, number in names.items() if name in text}
    return result or None


def _departure_datetime(
    departure_value: Any,
    predicted_dt: datetime | None,
    day_offset: Any = 0,
    runs_days: Any = None,
    next_occurrence: bool = False,
) -> datetime | None:
    """Place a stop on the incoming station date, respecting outgoing run days."""

    if predicted_dt is None:
        return None
    try:
        offset = int(float(day_offset or 0))
    except (TypeError, ValueError):
        offset = 0
    weekdays = _running_weekdays(runs_days)
    # An automatic onward connection is useful only within the next service
    # day. Do not present a train several days later as if it were a normal
    # passenger connection.
    dates = range(0, 2) if next_occurrence else range(0, 1)
    for day_delta in dates:
        station_date = predicted_dt.date() + timedelta(days=day_delta)
        origin_date = station_date - timedelta(days=offset)
        if weekdays is not None and origin_date.weekday() not in weekdays:
            continue
        parsed = _schedule_datetime(departure_value, origin_date, offset)
        if parsed is None:
            continue
        if next_occurrence and parsed <= predicted_dt:
            continue
        return parsed
    return None


def _connection_from_values(
    current_result: dict[str, Any],
    connecting_train_number: str,
    connecting_train_name: str | None,
    connection_station: str,
    current_station: dict[str, Any],
    departure_value: Any,
    day_offset: Any = 0,
    station_name: str | None = None,
    runs_days: Any = None,
    next_occurrence: bool = False,
) -> dict[str, Any]:
    predicted_arrival = current_station.get("predicted_arrival")
    predicted_dt = _schedule_datetime(predicted_arrival, date.today())
    departure_dt = _departure_datetime(
        departure_value,
        predicted_dt,
        day_offset,
        runs_days,
        next_occurrence,
    )
    if predicted_dt is None or departure_dt is None:
        return {
            "status": "unavailable",
            "reason": "The predicted arrival or connecting timetable departure has no usable timestamp.",
            "current_train_number": current_result.get("train_number"),
            "connecting_train_number": str(connecting_train_number),
            "connection_station": connection_station,
        }

    minimum_transfer = _minimum_transfer_minutes(connection_station)
    available_minutes = round((departure_dt - predicted_dt).total_seconds() / 60, 2)
    margin_minutes = round(available_minutes - minimum_transfer, 2)
    risk, recommendation = _risk_for_margin(available_minutes, margin_minutes)
    return {
        "status": "calculated",
        "current_train_number": current_result.get("train_number"),
        "connecting_train_number": str(connecting_train_number),
        "connecting_train_name": connecting_train_name,
        "connection_station": {
            "station_code": connection_station,
            "station_name": current_station.get("station_name") or station_name,
        },
        "predicted_arrival": predicted_arrival,
        "connecting_departure": departure_dt.isoformat(timespec="seconds"),
        "connecting_departure_type": "scheduled",
        "connection_time_minutes": available_minutes,
        "minimum_transfer_minutes": minimum_transfer,
        "connection_margin_minutes": margin_minutes,
        "risk": risk,
        "recommendation": recommendation,
        "thresholds_minutes": {
            "missed_at_or_before_departure": 0,
            "high_below_margin": 0,
            "medium_below_margin": _configured_minutes(
                "RAILETA_CONNECTION_MEDIUM_MARGIN_MINUTES",
                DEFAULT_MEDIUM_MARGIN_MINUTES,
            ),
        },
        "prediction_source": current_station.get("prediction_source"),
        "confidence": current_station.get("confidence"),
        "data_quality": "HIGH" if current_station.get("prediction_source") == "model" else "LOW",
        "data_sources": ["RailETA live ETA prediction", "local SQLite timetable"],
    }


def _connection_from_schedule(
    current_result: dict[str, Any],
    connecting_train_number: str,
    connection_station: str,
    current_station: dict[str, Any],
) -> dict[str, Any]:
    context = load_static_train_context(connecting_train_number)
    if context is None:
        return {
            "status": "unavailable",
            "reason": "The connecting train is not available in the local real timetable dataset.",
            "current_train_number": current_result.get("train_number"),
            "connecting_train_number": str(connecting_train_number),
            "connection_station": connection_station,
            "data_source": "local SQLite timetable",
        }
    connecting_train = context.get("train") if isinstance(context.get("train"), dict) else {}
    stop = next(
        (item for item in _route(context) if _station_code(item.get("stationCode")) == connection_station),
        None,
    )
    if stop is None:
        return {
            "status": "unavailable",
            "reason": "The connecting train has no timetable stop at the requested connection station.",
            "current_train_number": current_result.get("train_number"),
            "connecting_train_number": str(connecting_train_number),
            "connection_station": connection_station,
            "data_source": "local SQLite timetable",
        }
    return _connection_from_values(
        current_result,
        connecting_train_number,
        connecting_train.get("train_name"),
        connection_station,
        current_station,
        stop.get("scheduledDeparture") or stop.get("scheduledArrival"),
        stop.get("dayOffset", 0),
        stop.get("stationName"),
        connecting_train.get("runs_days"),
    )


def _empty_debug(current_result: dict[str, Any], schedule_source_status: str = "available") -> dict[str, Any]:
    stations = [item for item in current_result.get("stations", []) if isinstance(item, dict)]
    return {
        "train_number": current_result.get("train_number"),
        "prediction_available": bool(stations and stations[0].get("predicted_arrival")),
        "current_station": (current_result.get("current_position") or {}).get("station_code"),
        "remaining_route_stations": len(stations),
        "stations_checked": 0,
        "candidate_outgoing_trains_found": 0,
        "candidates_after_time_filter": 0,
        "candidates_after_transfer_filter": 0,
        "connections_evaluated": 0,
        "connections": [],
        "station_diagnostics": [],
        "rejection_reasons": {
            "no_schedule": 0,
            "same_train": 0,
            "departure_before_arrival": 0,
            "insufficient_transfer": 0,
            "invalid_station": 0,
            "missing_prediction": 0,
            "outside_24_hour_window": 0,
            "no_service_within_24_hours": 0,
        },
        "schedule_source": "local SQLite timetable",
        "schedule_source_status": schedule_source_status,
        "reason_code": None,
    }


def _automatic_discovery(current_result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Derive candidates across every remaining station from real timetable rows."""

    debug = _empty_debug(current_result)
    stations = [item for item in current_result.get("stations", []) if isinstance(item, dict)]
    if not stations:
        debug["reason_code"] = "no_remaining_route"
        return [], debug
    if not DEFAULT_DB_PATH.exists():
        debug["schedule_source_status"] = "unavailable"
        debug["reason_code"] = "schedule_source_unavailable"
        debug["rejection_reasons"]["no_schedule"] = len(stations)
        return [], debug

    candidates: list[dict[str, Any]] = []
    outgoing_numbers: set[str] = set()
    current_train = str(current_result.get("train_number") or "").strip()
    connection = None
    try:
        connection = sqlite3.connect(str(DEFAULT_DB_PATH))
        connection.row_factory = sqlite3.Row
        for current_station in stations:
            debug["stations_checked"] += 1
            station = _station_code(current_station.get("station_code"))
            predicted_dt = _schedule_datetime(current_station.get("predicted_arrival"), date.today())
            if not station:
                debug["rejection_reasons"]["invalid_station"] += 1
                continue
            if predicted_dt is None:
                debug["rejection_reasons"]["missing_prediction"] += 1
                continue
            rows = connection.execute(
                """
                SELECT ts.train_number, t.train_name, ts.departure_time,
                       ts.arrival_time, ts.day_offset, s.station_name,
                       t.runs_days
                FROM train_stops ts
                JOIN trains t ON t.train_number = ts.train_number
                LEFT JOIN stations s ON s.station_code = ts.station_code
                WHERE ts.station_code = ?
                ORDER BY ts.train_number
                """,
                (station,),
            ).fetchall()
            debug["station_diagnostics"].append(
                {
                    "station_code": station,
                    "station_name": current_station.get("station_name"),
                    "schedule_source_available": bool(rows),
                    "outgoing_train_count": len(rows),
                    "outgoing_trains": [
                        {
                            "train_number": str(row["train_number"] or "").strip(),
                            "train_name": row["train_name"],
                            "departure": row["departure_time"] or row["arrival_time"],
                            "day_offset": row["day_offset"],
                            "runs_days": row["runs_days"],
                        }
                        for row in rows
                    ],
                }
            )
            if not rows:
                debug["rejection_reasons"]["no_schedule"] += 1
                continue
            for row in rows:
                train_number = str(row["train_number"] or "").strip()
                outgoing_numbers.add(train_number)
                if train_number == current_train:
                    debug["rejection_reasons"]["same_train"] += 1
                    continue
                departure_value = row["departure_time"] or row["arrival_time"]
                if not departure_value:
                    debug["rejection_reasons"]["no_schedule"] += 1
                    continue
                debug["connections_evaluated"] += 1
                departure_dt = _departure_datetime(
                    departure_value,
                    predicted_dt,
                    row["day_offset"] or 0,
                    row["runs_days"],
                    True,
                )
                if departure_dt is None:
                    try:
                        offset = int(float(row["day_offset"] or 0))
                    except (TypeError, ValueError):
                        offset = 0
                    parse_check = _schedule_datetime(
                        departure_value,
                        predicted_dt.date() - timedelta(days=offset),
                        offset,
                    )
                    debug["rejection_reasons"][
                        "no_service_within_24_hours" if parse_check is not None else "no_schedule"
                    ] += 1
                    continue
                if departure_dt <= predicted_dt:
                    debug["rejection_reasons"]["departure_before_arrival"] += 1
                    continue
                if departure_dt > predicted_dt + timedelta(days=1):
                    debug["rejection_reasons"]["outside_24_hour_window"] += 1
                    continue
                debug["candidates_after_time_filter"] += 1
                candidate = _connection_from_values(
                    current_result,
                    train_number,
                    row["train_name"],
                    station,
                    current_station,
                    departure_value,
                    row["day_offset"] or 0,
                    row["station_name"],
                    row["runs_days"],
                    True,
                )
                if candidate.get("status") != "calculated":
                    debug["rejection_reasons"]["no_schedule"] += 1
                    continue
                if float(candidate.get("connection_margin_minutes", -1)) < 0:
                    debug["rejection_reasons"]["insufficient_transfer"] += 1
                    continue
                debug["candidates_after_transfer_filter"] += 1
                candidates.append(candidate)
        debug["candidate_outgoing_trains_found"] = len(outgoing_numbers)
    except sqlite3.Error:
        debug["schedule_source_status"] = "error"
        debug["reason_code"] = "schedule_source_error"
        return [], debug
    finally:
        if connection is not None:
            connection.close()

    candidates.sort(
        key=lambda item: (
            RISK_ORDER.get(str(item.get("risk")), 99),
            str(item.get("connecting_departure") or ""),
            -float(item.get("connection_margin_minutes", -1)),
        )
    )
    debug["connections"] = candidates
    if candidates:
        debug["reason_code"] = "valid_connections_found"
    elif debug["candidate_outgoing_trains_found"] == 0:
        debug["reason_code"] = "no_outgoing_trains_found"
    elif debug["rejection_reasons"]["departure_before_arrival"] == debug["connections_evaluated"]:
        debug["reason_code"] = "outgoing_trains_depart_before_predicted_arrival"
    elif debug["rejection_reasons"]["no_service_within_24_hours"] > 0:
        debug["reason_code"] = "no_outgoing_service_within_24_hours"
    elif debug["rejection_reasons"]["insufficient_transfer"] > 0:
        debug["reason_code"] = "insufficient_transfer_for_outgoing_trains"
    else:
        debug["reason_code"] = "no_valid_connection"
    return candidates, debug


def connection_debug(current_result: dict[str, Any]) -> dict[str, Any]:
    """Return non-sensitive diagnostics for automatic connection discovery."""

    _, debug = _automatic_discovery(current_result)
    return debug


def calculate_connection_risk(
    current_result: dict[str, Any],
    connecting_train_number: str | None = None,
    connection_station: str | None = None,
) -> dict[str, Any]:
    """Use shared ETA output and real scheduled departures to calculate risk."""

    current_stations = [item for item in current_result.get("stations", []) if isinstance(item, dict)]
    selected_code = _station_code(
        connection_station or ((current_result.get("next_station") or {}).get("station_code"))
    )
    current_station = next(
        (item for item in current_stations if _station_code(item.get("station_code")) == selected_code),
        None,
    )
    if current_station is None:
        return {
            "status": "unavailable",
            "reason": "The requested connection station is not in the current train's returned upcoming route.",
            "current_train_number": current_result.get("train_number"),
            "connecting_train_number": connecting_train_number,
            "connection_station": selected_code,
        }

    if connecting_train_number:
        return _connection_from_schedule(
            current_result,
            str(connecting_train_number).strip(),
            selected_code,
            current_station,
        )

    candidates, debug = _automatic_discovery(current_result)
    if not candidates:
        return {
            "status": "unavailable",
            "reason": "No connecting journey detected from the available local timetable.",
            "reason_code": debug.get("reason_code"),
            "current_train_number": current_result.get("train_number"),
            "connection_station": selected_code,
            "automatic_detection": True,
            "candidates": [],
            "diagnostics": debug,
            "data_source": "local SQLite timetable",
        }
    selected = dict(candidates[0])
    selected["automatic_detection"] = True
    selected["candidates"] = candidates
    selected["candidate_count"] = len(candidates)
    selected["diagnostics"] = debug
    return selected
