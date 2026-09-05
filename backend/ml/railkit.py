from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment,misc]

from .contract import DataUnavailableError


IST = ZoneInfo("Asia/Kolkata") if ZoneInfo is not None else None
EVENT_COLUMNS = [
    "train_number",
    "journey_date",
    "station_code",
    "station_name",
    "sequence",
    "distance_from_origin",
    "scheduled_arrival",
    "actual_arrival",
    "scheduled_departure",
    "actual_departure",
    "arrival_delay_minutes",
    "departure_delay_minutes",
    "status",
    "platform",
    "source_delay_minutes",
    "source",
    "data_source",
    "collected_at",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _backend_root() -> Path:
    return _project_root() / "backend"


def _default_cache_dir() -> Path:
    return _backend_root() / "ml" / "data" / "raw" / "railkit"


def _default_usage_path() -> Path:
    return _backend_root() / "data" / "railkit_usage.json"


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(0, int(raw))
    except ValueError as exc:
        raise DataUnavailableError(f"{name} must be an integer, got {raw!r}.") from exc


def _read_optional_nonnegative_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return _read_int_env(name, 0)


def _parse_journey_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise DataUnavailableError(
        f"Invalid journey date {value!r}; use YYYY-MM-DD or DD-MM-YYYY."
    )


def _provider_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def _safe_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_" else "_" for character in value)


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _nested(mapping: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    value = _pick(mapping, *keys)
    if isinstance(value, dict):
        return _pick(value, "time", "timestamp", "value", "datetime")
    return value


def _as_timestamp(raw: Any, journey_day: date, previous: datetime | None) -> str | None:
    if raw in (None, ""):
        return None

    if isinstance(raw, (int, float)):
        parsed = datetime.fromtimestamp(raw, tz=IST)

    else:
        text = str(raw).strip()

        if text.upper() in {"SRC", "DSTN"}:
            return None

        parsed = None

        # ISO timestamps.
        iso_text = text.replace("Z", "+00:00")

        try:
            parsed = datetime.fromisoformat(iso_text)
        except ValueError:
            pass

        # Full date/time formats.
        if parsed is None:
            for pattern in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%d-%m-%Y %H:%M:%S",
                "%d-%m-%Y %H:%M",
            ):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue

        # RailKit format, e.g. "18:47 11-Jun".
        if parsed is None:
            try:
                parsed = datetime.strptime(
                    f"{text} {journey_day.year}",
                    "%H:%M %d-%b %Y",
                )

                # Handle journeys crossing New Year.
                if parsed.date() < journey_day - timedelta(days=1):
                    parsed = parsed.replace(year=journey_day.year + 1)

            except ValueError:
                parsed = None

        # Time-only fallback.
        if parsed is None:
            for pattern in ("%H:%M:%S", "%H:%M"):
                try:
                    parsed_time = datetime.strptime(text, pattern).time()
                    parsed = datetime.combine(journey_day, parsed_time)

                    comparable_previous = previous

                    if (
                        comparable_previous is not None
                        and comparable_previous.tzinfo is not None
                    ):
                        comparable_previous = comparable_previous.replace(
                            tzinfo=None
                        )

                    if (
                        comparable_previous is not None
                        and parsed < comparable_previous
                    ):
                        parsed += timedelta(days=1)

                    break

                except ValueError:
                    continue

        if parsed is None:
            return None

    if parsed.tzinfo is None and IST is not None:
        parsed = parsed.replace(tzinfo=IST)

    if parsed.tzinfo is not None and IST is not None:
        parsed = parsed.astimezone(IST)

    return parsed.isoformat(timespec="seconds")

def _as_delay_minutes(raw: Any) -> int | float | None:
    if raw in (None, ""):
        return None

    text = str(raw).strip().lower()

    if text in {"on time", "ontime"}:
        return 0

    match = re.search(r"-?\d+(?:\.\d+)?", text)

    if match is None:
        return None

    value = float(match.group())

    if value.is_integer():
        return int(value)

    return value


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    return data if isinstance(data, dict) else {}


def normalize_history(payload: dict[str, Any], requested_train: str, requested_date: str) -> list[dict[str, Any]]:
    """Convert a RailKit train-history response to the model's event contract."""

    if payload.get("success") is False:
        provider_error = payload.get("error") or payload.get("message") or "unknown provider error"
        raise DataUnavailableError(f"RailKit provider error: {provider_error}")

    data = _payload_data(payload)
    journey_day = _parse_journey_date(str(data.get("journeyDate") or requested_date))
    train_number = str(
        data.get("trainNumber")
        or data.get("trainNo")
        or (data.get("train") or {}).get("number")
        or requested_train
    )
    stops = data.get("stations") or data.get("stops") or data.get("timeline") or []
    if not isinstance(stops, list):
        raise DataUnavailableError("RailKit history response did not contain a station list.")

    records: list[dict[str, Any]] = []
    previous_scheduled: datetime | None = None
    previous_actual: datetime | None = None
    for index, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue
        arrival = stop.get("arrival") if isinstance(stop.get("arrival"), dict) else {}
        departure = stop.get("departure") if isinstance(stop.get("departure"), dict) else {}

        station_code = _pick(stop, "stationCode", "station_code", "code")
        station_name = _pick(stop, "stationName", "station_name", "name")
        distance_from_origin = _pick(
            stop,
            "distanceKm",
            "distance_km",
            "distanceFromOrigin",
            "distance_from_origin",
        )
        scheduled_arrival = _as_timestamp(
            _nested(arrival, "scheduled", "scheduledTime", "schedule"),
            journey_day,
            previous_scheduled,
        )
        actual_arrival = _as_timestamp(
            _nested(arrival, "actual", "actualTime", "actualArrival"),
            journey_day,
            previous_actual or (datetime.fromisoformat(scheduled_arrival) if scheduled_arrival else None),
        )
        scheduled_departure = _as_timestamp(
            _nested(departure, "scheduled", "scheduledTime", "schedule"),
            journey_day,
            datetime.fromisoformat(scheduled_arrival) if scheduled_arrival else previous_scheduled,
        )
        actual_departure = _as_timestamp(
            _nested(departure, "actual", "actualTime", "actualDeparture"),
            journey_day,
            datetime.fromisoformat(actual_arrival) if actual_arrival else previous_actual,
        )
        if scheduled_arrival:
            previous_scheduled = datetime.fromisoformat(scheduled_arrival)
        if actual_arrival:
            previous_actual = datetime.fromisoformat(actual_arrival)
        if scheduled_departure:
            previous_scheduled = datetime.fromisoformat(scheduled_departure)
        if actual_departure:
            previous_actual = datetime.fromisoformat(actual_departure)

        if not station_code and not station_name:
            continue
        source_delay = _as_delay_minutes(
        	_nested(arrival, "delay", "delayMinutes")
        )

        departure_delay = _as_delay_minutes(
       		_nested(departure, "delay", "delayMinutes")
        )
        records.append(
            {
                "train_number": train_number,
                "journey_date": journey_day.isoformat(),
                "station_code": str(station_code or "").strip(),
                "station_name": str(station_name or "").strip(),
                "sequence": index,
                "distance_from_origin": distance_from_origin if distance_from_origin is not None else "",
                "scheduled_arrival": scheduled_arrival or "",
                "actual_arrival": actual_arrival or "",
                "scheduled_departure": scheduled_departure or "",
                "actual_departure": actual_departure or "",
                "arrival_delay_minutes": source_delay if source_delay is not None else "",
                "departure_delay_minutes": departure_delay if departure_delay is not None else "",
                "status": str(_pick(stop, "status", "eventStatus") or "").strip(),
                "platform": str(_pick(stop, "platform", "platformNumber") or "").strip(),
                "source_delay_minutes": source_delay if source_delay is not None else "",
                "source": "railkit",
                "data_source": "RailKit Train History API",
                "collected_at": datetime.now(IST).isoformat(timespec="seconds") if IST is not None else datetime.now().isoformat(timespec="seconds"),
            }
        )
    return records


class RailKitHistoryClient:
    """Quota-aware, cache-first client for the official RailKit Node SDK."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        usage_path: Path | None = None,
        bridge_dir: Path | None = None,
        monthly_limit: int | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or os.getenv("RAILKIT_CACHE_DIR") or _default_cache_dir())
        self.usage_path = Path(usage_path or os.getenv("RAILKIT_USAGE_FILE") or _default_usage_path())
        self.bridge_dir = Path(bridge_dir or _backend_root() / "integrations" / "railkit")
        self.monthly_limit = (
            _read_int_env("RAILKIT_MAX_MONTHLY_REQUESTS", 0)
            if monthly_limit is None
            else max(0, monthly_limit)
        )
        self.provider_remaining = _read_optional_nonnegative_env(
            "RAILKIT_PROVIDER_REMAINING_REQUESTS"
        )

    def _cache_path(self, train_number: str, journey_day: date) -> Path:
        return self.cache_dir / _safe_component(train_number) / f"{journey_day.strftime('%d-%m-%Y')}.json"

    def cache_path_for(self, train_number: str, journey_date: str) -> Path:
        """Return the deterministic cache path without making a request."""

        return self._cache_path(train_number, _parse_journey_date(journey_date))

    def is_cached(self, train_number: str, journey_date: str) -> bool:
        return self.cache_path_for(train_number, journey_date).exists()

    def _local_usage_for_month(self, month: str) -> int:
        if not self.usage_path.exists():
            return 0
        try:
            with self.usage_path.open("r", encoding="utf-8") as handle:
                usage = json.load(handle)
            return int((usage.get("months") or {}).get(month, 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise DataUnavailableError(f"Could not read RailKit request ledger at {self.usage_path}.") from exc

    def _provider_implied_usage(self) -> int:
        if self.monthly_limit <= 0 or self.provider_remaining is None:
            return 0
        return max(0, self.monthly_limit - self.provider_remaining)

    def quota_status(self) -> dict[str, int | str | None]:
        """Return the current monthly safety budget without reserving a request."""

        month = datetime.now(IST).strftime("%Y-%m") if IST is not None else datetime.now().strftime("%Y-%m")
        locally_recorded_usage = self._local_usage_for_month(month)
        provider_implied_usage = self._provider_implied_usage()
        used = max(locally_recorded_usage, provider_implied_usage)
        local_remaining = max(0, self.monthly_limit - used) if self.monthly_limit > 0 else 0
        remaining = (
            min(local_remaining, self.provider_remaining)
            if self.provider_remaining is not None and self.monthly_limit > 0
            else local_remaining
        )
        return {
            "month": month,
            "limit": self.monthly_limit,
            "locally_recorded_usage": locally_recorded_usage,
            "provider_reported_remaining": self.provider_remaining,
            "provider_implied_usage": provider_implied_usage,
            "used": used,
            "remaining": remaining,
        }

    def _read_cached(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise DataUnavailableError(f"Could not read cached RailKit response at {path}.") from exc
        if not isinstance(payload, dict):
            raise DataUnavailableError(f"Cached RailKit response at {path} is not a JSON object.")
        return payload

    def _reserve_request(self) -> None:
        if self.monthly_limit <= 0:
            raise DataUnavailableError(
                "RailKit ingestion is disabled. Set RAILKIT_MAX_MONTHLY_REQUESTS in backend/.env "
                "to a positive value before fetching history."
            )
        month = datetime.now(IST).strftime("%Y-%m") if IST is not None else datetime.now().strftime("%Y-%m")
        usage: dict[str, Any] = {}
        if self.usage_path.exists():
            try:
                with self.usage_path.open("r", encoding="utf-8") as handle:
                    usage = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise DataUnavailableError(f"Could not read RailKit request ledger at {self.usage_path}.") from exc
        locally_recorded_usage = int((usage.get("months") or {}).get(month, 0))
        used = max(locally_recorded_usage, self._provider_implied_usage())
        if used >= self.monthly_limit:
            raise DataUnavailableError(
                f"RailKit monthly safety limit reached ({used}/{self.monthly_limit}) for {month}. "
                "Use cached responses or raise the limit intentionally in backend/.env."
            )
        usage.setdefault("months", {})[month] = used + 1
        usage["last_reserved_at"] = datetime.now(IST).isoformat(timespec="seconds") if IST is not None else datetime.now().isoformat(timespec="seconds")
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.usage_path.parent, delete=False) as handle:
            json.dump(usage, handle, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, self.usage_path)

    def fetch_history(self, train_number: str, journey_date: str, force: bool = False) -> dict[str, Any]:
        journey_day = _parse_journey_date(journey_date)
        cache_path = self._cache_path(train_number, journey_day)
        if not force:
            cached = self._read_cached(cache_path)
            if cached is not None:
                return cached

        api_key = os.getenv("RAILKIT_API_KEY", "").strip()
        if not api_key:
            raise DataUnavailableError(
                "RAILKIT_API_KEY is not configured. Add it only to the ignored backend/.env file."
            )
        bridge_script = self.bridge_dir / "fetch_history.mjs"
        package_dir = self.bridge_dir / "node_modules"
        if not bridge_script.exists() or not package_dir.exists():
            raise DataUnavailableError(
                "RailKit SDK is not installed. Run npm install in backend/integrations/railkit "
                "before fetching history."
            )

        self._reserve_request()
        environment = os.environ.copy()
        result = subprocess.run(
            ["node", str(bridge_script), str(train_number), _provider_date(journey_day)],
            cwd=str(self.bridge_dir),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or "RailKit returned an unsuccessful response."
            raise DataUnavailableError(message)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise DataUnavailableError("RailKit returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise DataUnavailableError("RailKit returned a JSON value instead of an object.")
        if payload.get("success") is False:
            provider_error = payload.get("error") or payload.get("message") or "unknown provider error"
            raise DataUnavailableError(f"RailKit provider error: {provider_error}")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, cache_path)
        return payload


def merge_events(path: Path, records: list[dict[str, Any]]) -> int:
    """Upsert normalized events without overwriting unrelated source rows."""

    existing: list[dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))

    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in existing + records:
        key = (
            str(row.get("train_number", "")),
            str(row.get("journey_date", "")),
            str(row.get("station_code", "")),
            str(row.get("sequence", "")),
        )
        merged[key] = row

    rows = sorted(merged.values(), key=lambda row: (
        str(row.get("journey_date", "")),
        str(row.get("train_number", "")),
        int(row.get("sequence", 0) or 0),
    ))
    fieldnames = list(EVENT_COLUMNS)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return len(records)
