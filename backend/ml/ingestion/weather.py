from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    httpx = None  # type: ignore[assignment]

from ..contract import DataUnavailableError, require_file


WEATHER_COLUMNS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "weather_code",
]
WEATHER_SOURCE = "Open-Meteo Historical Weather API"
DEFAULT_URL = "https://archive-api.open-meteo.com/v1/archive"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_stations_path() -> Path:
    root = _repo_root()
    geocoded = root / "backend" / "data" / "stations_geocoded.csv"
    processed = root / "backend" / "data" / "processed" / "stations.csv"
    return geocoded if geocoded.exists() else processed


def _parse_timestamp(value: str) -> datetime | None:
    if not value or value in {"SRC", "--"}:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed


def _date_from_event(row: dict[str, str]) -> date | None:
    event_time = (
        row.get("actual_departure")
        or row.get("scheduled_departure")
        or row.get("actual_arrival")
        or row.get("scheduled_arrival")
    )
    parsed = _parse_timestamp(event_time)
    if parsed is not None:
        return parsed.date()
    try:
        return date.fromisoformat(str(row.get("journey_date", ""))[:10])
    except ValueError:
        return None


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


class OpenMeteoHistoricalClient:
    """Cache-first client for one Open-Meteo weather day per coordinate."""

    def __init__(self, cache_dir: Path | None = None, base_url: str | None = None) -> None:
        self.cache_dir = Path(
            cache_dir
            or os.getenv("OPEN_METEO_HISTORICAL_CACHE_DIR")
            or _repo_root() / "backend" / "ml" / "data" / "raw" / "weather"
        )
        self.base_url = base_url or os.getenv("OPEN_METEO_HISTORICAL_URL") or DEFAULT_URL

    def _cache_path(self, latitude: float, longitude: float, day: date) -> Path:
        return self.cache_dir / f"{latitude:.4f}_{longitude:.4f}_{day.isoformat()}.json"

    def fetch_day(self, latitude: float, longitude: float, day: date) -> tuple[dict[str, Any], bool]:
        cache_path = self._cache_path(latitude, longitude, day)
        if cache_path.exists():
            try:
                with cache_path.open("r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload, True
            except (OSError, json.JSONDecodeError):
                pass

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": day.isoformat(),
            "end_date": day.isoformat(),
            "hourly": ",".join(WEATHER_COLUMNS),
            "timezone": "Asia/Kolkata",
        }
        if httpx is None:
            raise DataUnavailableError("httpx is not installed. Install backend/requirements.txt before fetching weather.")
        try:
            response = httpx.get(self.base_url, params=params, timeout=30.0)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise DataUnavailableError(
                f"Open-Meteo historical request failed with HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise DataUnavailableError(f"Open-Meteo historical request failed: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
            raise DataUnavailableError("Open-Meteo historical response did not contain hourly data.")
        _atomic_json_write(cache_path, payload)
        return payload, False


def nearest_weather(payload: dict[str, Any], event_time: datetime, max_hours: int = 3) -> dict[str, Any] | None:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        return None
    candidates: list[tuple[float, int, datetime]] = []
    for index, raw_time in enumerate(hourly["time"]):
        parsed = _parse_timestamp(str(raw_time))
        if parsed is None:
            continue
        if event_time.tzinfo is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=event_time.tzinfo)
        delta_hours = abs((parsed - event_time).total_seconds()) / 3600.0
        candidates.append((delta_hours, index, parsed))
    if not candidates:
        return None
    delta_hours, index, matched_time = min(candidates, key=lambda item: item[0])
    if delta_hours > max_hours:
        return None
    row: dict[str, Any] = {
        "timestamp": matched_time.isoformat(timespec="minutes"),
        "match_delta_minutes": round(delta_hours * 60, 2),
    }
    for column in WEATHER_COLUMNS:
        values = hourly.get(column)
        row[column] = values[index] if isinstance(values, list) and index < len(values) else None
    return row


def _read_csv(path: Path, description: str) -> list[dict[str, str]]:
    require_file(path, description)
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def augment_events(
    events_path: Path,
    stations_path: Path,
    weather_output: Path,
    report_path: Path,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    events = _read_csv(events_path, "RailKit running events")
    stations = _read_csv(stations_path, "station coordinates")
    station_lookup: dict[str, tuple[float, float]] = {}
    for station in stations:
        try:
            latitude = float(station.get("lat") or station.get("latitude"))
            longitude = float(station.get("lon") or station.get("longitude"))
        except (TypeError, ValueError):
            continue
        station_lookup[str(station.get("code") or station.get("station_code") or "").strip()] = (latitude, longitude)

    client = OpenMeteoHistoricalClient(cache_dir=cache_dir)
    unique_requests: dict[tuple[str, float, float], dict[str, Any]] = {}
    skipped_no_coordinates = 0
    skipped_no_time = 0
    for row in events:
        station_code = str(row.get("station_code", "")).strip()
        coordinates = station_lookup.get(station_code)
        event_time = _parse_timestamp(
            row.get("actual_departure")
            or row.get("scheduled_departure")
            or row.get("actual_arrival")
            or row.get("scheduled_arrival")
        )
        if coordinates is None:
            skipped_no_coordinates += 1
            continue
        if event_time is None:
            skipped_no_time += 1
            continue
        key = (event_time.date().isoformat(), round(coordinates[0], 4), round(coordinates[1], 4))
        unique_requests.setdefault(key, {"coordinates": coordinates, "day": event_time.date()})

    weather_by_request: dict[tuple[str, float, float], dict[str, Any]] = {}
    cache_hits = 0
    for key, request in unique_requests.items():
        payload, from_cache = client.fetch_day(*request["coordinates"], request["day"])
        cache_hits += int(from_cache)
        weather_by_request[key] = payload

    weather_rows: list[dict[str, Any]] = []
    matched_events = 0
    for row in events:
        station_code = str(row.get("station_code", "")).strip()
        coordinates = station_lookup.get(station_code)
        event_time = _parse_timestamp(
            row.get("actual_departure")
            or row.get("scheduled_departure")
            or row.get("actual_arrival")
            or row.get("scheduled_arrival")
        )
        if coordinates is None or event_time is None:
            continue
        key = (event_time.date().isoformat(), round(coordinates[0], 4), round(coordinates[1], 4))
        matched = nearest_weather(weather_by_request[key], event_time)
        if matched is None:
            continue
        matched_events += 1
        for column in WEATHER_COLUMNS:
            row[column] = matched.get(column)
        row["weather_match_delta_minutes"] = matched.get("match_delta_minutes")
        row["weather_source"] = WEATHER_SOURCE
        weather_rows.append(
            {
                "timestamp": matched.get("timestamp"),
                "latitude": coordinates[0],
                "longitude": coordinates[1],
                "station_code": station_code,
                **{column: matched.get(column) for column in WEATHER_COLUMNS},
                "match_delta_minutes": matched.get("match_delta_minutes"),
                "source": WEATHER_SOURCE,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    event_columns = list(events[0].keys()) if events else []
    for column in (*WEATHER_COLUMNS, "weather_match_delta_minutes", "weather_source"):
        if column not in event_columns:
            event_columns.append(column)
    _write_csv(events_path, events, event_columns)
    weather_columns = [
        "timestamp", "latitude", "longitude", "station_code", *WEATHER_COLUMNS,
        "match_delta_minutes", "source", "collected_at",
    ]
    _write_csv(weather_output, weather_rows, weather_columns)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": WEATHER_SOURCE,
        "events": len(events),
        "unique_coordinate_days": len(unique_requests),
        "weather_requests_from_cache": cache_hits,
        "weather_requests_fetched": len(unique_requests) - cache_hits,
        "matched_events": matched_events,
        "weather_match_percentage": round((matched_events / len(events)) * 100, 2) if events else 0.0,
        "unmatched_events": len(events) - matched_events,
        "skipped_missing_coordinates": skipped_no_coordinates,
        "skipped_missing_event_time": skipped_no_time,
        "matching_rule": "nearest hourly observation within 3 hours of actual departure, then scheduled departure or arrival fallback",
        "variables": WEATHER_COLUMNS,
        "weather_output": str(weather_output),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description="Match real Open-Meteo historical weather to RailKit events.")
    parser.add_argument("--events", type=Path, default=root / "backend" / "data" / "processed" / "running_events.csv")
    parser.add_argument("--stations", type=Path, default=_default_stations_path())
    parser.add_argument("--output", type=Path, default=root / "backend" / "data" / "processed" / "historical_weather.csv")
    parser.add_argument("--report", type=Path, default=root / "backend" / "ml" / "data" / "historical_weather_report.json")
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()
    report = augment_events(args.events, args.stations, args.output, args.report, args.cache_dir)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
