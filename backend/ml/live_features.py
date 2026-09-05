from __future__ import annotations

import math
import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .contract import DataUnavailableError
from .features import build_weather_feature_values


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def _nested(mapping: dict[str, Any], parent: str, *keys: str) -> Any:
    value = mapping.get(parent)
    if not isinstance(value, dict):
        return None
    for key in keys:
        if value.get(key) not in (None, "", "--", "SRC"):
            return value[key]
    return None


def _value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if mapping.get(key) not in (None, "", "--", "SRC"):
            return mapping[key]
    return None


def _text(value: Any, *nested_keys: str) -> str | None:
    """Return a scalar categorical value from RailRadar's mixed JSON shapes."""

    if isinstance(value, dict):
        for key in (*nested_keys, "code", "stationCode", "station_code", "number", "name", "type", "value"):
            nested = value.get(key)
            if nested not in (None, "", "--", "SRC") and not isinstance(nested, (dict, list, tuple)):
                return str(nested).strip()
        return None
    if isinstance(value, (list, tuple)) or value in (None, "", "--", "SRC"):
        return None
    return str(value).strip()


def _float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _clock_minutes(value: Any) -> float | None:
    if value in (None, "", "--", "SRC"):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.hour * 60 + parsed.minute
    except ValueError:
        pass
    try:
        hours, minutes = text.split(":")[:2]
        return int(hours) * 60 + int(minutes)
    except (ValueError, TypeError):
        return None


def _schedule_datetime(value: Any, reference_day: date, day_offset: Any = 0) -> datetime | None:
    if value in (None, "", "--", "SRC"):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    minutes = _clock_minutes(text)
    if minutes is None:
        return None
    try:
        offset = int(float(day_offset or 0))
    except (TypeError, ValueError):
        offset = 0
    return datetime.combine(reference_day + timedelta(days=offset), datetime.min.time()) + timedelta(minutes=minutes)


def _timestamp(value: Any, reference_day: date, day_offset: Any = 0) -> str | None:
    parsed = _schedule_datetime(value, reference_day, day_offset)
    return parsed.isoformat(timespec="seconds") if parsed is not None else None


def _coordinates(stop: dict[str, Any]) -> tuple[float, float] | None:
    nested = stop.get("coordinates")
    latitude_value = _value(stop, "lat", "latitude")
    longitude_value = _value(stop, "lng", "lon", "longitude")
    if isinstance(nested, dict):
        latitude_value = latitude_value or nested.get("latitude")
        longitude_value = longitude_value or nested.get("longitude")
    latitude = _float(latitude_value)
    longitude = _float(longitude_value)
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def _distance_km(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    direct = _float(_value(second, "sectionDistanceKm", "section_distance_km"))
    if direct is not None:
        return direct
    a = _coordinates(first)
    b = _coordinates(second)
    if a is None or b is None:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    haversine = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(haversine))


def _route(data: dict[str, Any]) -> list[dict[str, Any]]:
    route = data.get("route")
    if isinstance(route, dict):
        route = route.get("stops") or route.get("stations")
    if not isinstance(route, list):
        route = data.get("timeline")
    if not isinstance(route, list):
        return []
    result = [stop for stop in route if isinstance(stop, dict)]
    result.sort(key=lambda stop: _float(_value(stop, "sequence", "seq")) or 0)
    return result


def current_coordinates(payload: dict[str, Any]) -> tuple[float, float] | None:
    data = _unwrap(payload)
    location = data.get("currentLocation") if isinstance(data.get("currentLocation"), dict) else {}
    coordinates = _coordinates(location)
    if coordinates is not None:
        return coordinates
    route = _route(data)
    current_code = _text(_value(location, "stationCode", "station_code"), "stationCode", "station_code")
    if current_code:
        for stop in route:
            if _text(_value(stop, "stationCode", "station_code", "code"), "stationCode", "station_code", "code") == current_code:
                coordinates = _coordinates(stop)
                if coordinates is not None:
                    return coordinates
    for stop in route:
        if str(_value(stop, "status") or "").lower() == "current":
            coordinates = _coordinates(stop)
            if coordinates is not None:
                return coordinates
    return None


def build_live_rows(payload: dict[str, Any], weather: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Translate RailRadar's live route into the trained section feature schema."""

    data = _unwrap(payload)
    route = _route(data)
    if not route:
        raise DataUnavailableError("RailRadar did not return a usable route for live ETA prediction.")
    current_location = data.get("currentLocation") if isinstance(data.get("currentLocation"), dict) else {}
    current_code = _text(_value(current_location, "stationCode", "station_code"), "stationCode", "station_code")
    current_sequence = _float(_value(current_location, "sequence", "seq"))
    current_index = None
    if current_code:
        current_index = next(
            (
                index
                for index, stop in enumerate(route)
                if _text(_value(stop, "stationCode", "station_code", "code"), "stationCode", "station_code", "code") == current_code
            ),
            None,
        )
    if current_index is None and current_sequence is not None:
        current_index = max((index for index, stop in enumerate(route) if (_float(_value(stop, "sequence", "seq")) or 0) <= current_sequence), default=0)
    if current_index is None:
        current_index = next((index for index, stop in enumerate(route) if str(_value(stop, "status") or "").lower() == "current"), 0)
    current_stop = route[current_index]
    future_stops = [
        stop for stop in route[current_index + 1 :]
        if _value(stop, "isHalt") is not False and str(_value(stop, "status") or "upcoming").lower() in {"upcoming", "approaching", "arriving", "current", ""}
    ]
    if not future_stops:
        future_stops = [stop for stop in route[current_index + 1 :] if _value(stop, "isHalt") is not False]
    train = data.get("train") if isinstance(data.get("train"), dict) else {}
    train_number = _text(
        _value(data, "trainNumber", "trainNo") or _value(train, "number", "trainNumber"),
        "trainNumber",
        "trainNo",
        "number",
    ) or ""
    train_type = _text(_value(data, "trainType") or _value(train, "type"), "type", "code", "name")
    source = _text(
        _value(data, "sourceStationCode") or _value(train, "sourceCode") or _value(train, "source"),
        "stationCode",
        "station_code",
        "code",
    )
    destination = _text(
        _value(data, "destinationStationCode") or _value(train, "destinationCode") or _value(train, "destination"),
        "stationCode",
        "station_code",
        "code",
    )
    current_delay = _float(_value(data, "delayMinutes", "currentDelayMinutes", "delay", "lateBy"))
    reference_day = date.today()
    weather = weather or {}
    rows: list[dict[str, Any]] = []
    for target in future_stops:
        current_arrival = _value(current_stop, "actualArrival") or _nested(current_stop, "arrival", "actual", "actualTime")
        current_scheduled_arrival = _value(current_stop, "scheduledArrival") or _nested(current_stop, "arrival", "scheduled", "scheduledTime")
        current_departure = _value(current_stop, "actualDeparture") or _nested(current_stop, "departure", "actual", "actualTime")
        current_scheduled_departure = _value(current_stop, "scheduledDeparture") or _nested(current_stop, "departure", "scheduled", "scheduledTime")
        next_scheduled = _value(target, "scheduledArrival") or _nested(target, "arrival", "scheduled", "scheduledTime")
        current_day_offset = _float(_value(current_stop, "dayOffset", "day")) or 0
        next_day_offset = _float(_value(target, "dayOffset", "day")) or current_day_offset
        next_scheduled_timestamp = _timestamp(next_scheduled, reference_day, next_day_offset)
        next_code = _text(_value(target, "stationCode", "station_code", "code"), "stationCode", "station_code", "code")
        current_station = _text(
            _value(current_stop, "stationCode", "station_code", "code"),
            "stationCode",
            "station_code",
            "code",
        )
        section_runtime = None
        start_datetime = _schedule_datetime(
            current_scheduled_departure or current_scheduled_arrival,
            reference_day,
            current_day_offset,
        )
        end_datetime = _schedule_datetime(next_scheduled, reference_day, next_day_offset)
        if start_datetime is not None and end_datetime is not None:
            section_runtime = (end_datetime - start_datetime).total_seconds() / 60
            if section_runtime < 0:
                section_runtime += 1440
        row = {
            "journey_date": reference_day.isoformat(),
            "train_number": train_number,
            "train_type": train_type,
            "previous_station_code": (
                _text(
                    _value(route[max(0, current_index - 1)], "stationCode", "station_code", "code"),
                    "stationCode",
                    "station_code",
                    "code",
                )
                if current_index
                else None
            ),
            "current_station_code": current_station,
            "next_station_code": next_code,
            "source_station_code": source,
            "destination_station_code": destination,
            "section_id": f"{current_station or ''}:{next_code or ''}",
            "station_sequence": _float(_value(current_stop, "sequence", "seq")),
            "day_offset": next_day_offset,
            "section_distance_km": _distance_km(current_stop, target),
            "scheduled_section_runtime_minutes": section_runtime,
            "scheduled_halt_duration_minutes": None,
            "actual_halt_duration_minutes": None,
            "current_arrival_delay_minutes": current_delay,
            "current_departure_delay_minutes": current_delay,
            "previous_arrival_delay_minutes": None,
            "previous_departure_delay_minutes": None,
            "historical_train_delay_mean": None,
            "historical_train_station_delay_mean": None,
            "historical_station_delay_mean": None,
            "historical_section_runtime_mean": None,
            "historical_section_runtime_median": None,
            "historical_section_runtime_std": None,
            "day_of_week": reference_day.weekday(),
            "month": reference_day.month,
            "hour_of_day": (
                _clock_minutes(current_scheduled_departure or current_scheduled_arrival) / 60
                if _clock_minutes(current_scheduled_departure or current_scheduled_arrival) is not None
                else None
            ),
            "scheduled_next_arrival": next_scheduled_timestamp or next_scheduled,
            "scheduled_next_departure": _value(target, "scheduledDeparture") or _nested(target, "departure", "scheduled", "scheduledTime"),
            "next_station_sequence": _float(_value(target, "sequence", "seq")),
            "next_station_name": _text(
                _value(target, "stationName", "station_name", "name"),
                "stationName",
                "station_name",
                "name",
            ),
        }
        row.update(build_weather_feature_values(weather))
        rows.append(row)
    return rows


def add_historical_aggregates(rows: list[dict[str, Any]], feature_store: Path) -> list[dict[str, Any]]:
    """Attach only already-materialized historical aggregates to live rows."""

    if not feature_store.exists():
        return rows
    with feature_store.open(newline="", encoding="utf-8") as handle:
        stored = list(csv.DictReader(handle))
    aggregate_columns = (
        "historical_train_delay_mean",
        "historical_train_station_delay_mean",
        "historical_station_delay_mean",
        "historical_section_runtime_mean",
        "historical_section_runtime_median",
        "historical_section_runtime_std",
    )
    stored.sort(key=lambda row: row.get("journey_date", ""))
    for row in rows:
        candidates = [
            item for item in stored
            if item.get("train_number") == row.get("train_number")
            and item.get("current_station_code") == row.get("current_station_code")
            and item.get("next_station_code") == row.get("next_station_code")
        ]
        if not candidates:
            candidates = [
                item for item in stored
                if item.get("current_station_code") == row.get("current_station_code")
                and item.get("next_station_code") == row.get("next_station_code")
            ]
        if not candidates:
            continue
        latest = candidates[-1]
        for column in aggregate_columns:
            if latest.get(column) not in (None, ""):
                try:
                    row[column] = float(latest[column])
                except ValueError:
                    pass
    return rows
