from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_EVENT_COLUMNS = (
    "train_number",
    "journey_date",
    "station_code",
    "sequence",
    "scheduled_arrival",
    "actual_arrival",
)

OPTIONAL_EVENT_COLUMNS = (
    "station_name",
    "distance_from_origin",
    "actual_departure",
    "scheduled_departure",
    "arrival_delay_minutes",
    "departure_delay_minutes",
    "status",
    "platform",
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "weather_code",
)


@dataclass(frozen=True)
class DataUnavailableError(Exception):
    """Raised when a real training source is missing or unusable."""

    message: str

    def __str__(self) -> str:
        return self.message


def require_file(path: Path, description: str) -> Path:
    if not path.exists():
        raise DataUnavailableError(
            f"DATA SOURCE ACCESS REQUIRED: {description} was not found at {path}. "
            "No synthetic training data will be generated."
        )
    return path


def validate_event_columns(columns: list[str]) -> None:
    missing = [column for column in REQUIRED_EVENT_COLUMNS if column not in columns]
    if missing:
        raise DataUnavailableError(
            "DATA SOURCE ACCESS REQUIRED: running_events.csv is missing required "
            f"columns: {', '.join(missing)}. Expected an event-level RailKit export "
            "with scheduled and actual arrival timestamps."
        )
