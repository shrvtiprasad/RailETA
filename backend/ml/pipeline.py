from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contract import DataUnavailableError
from .features import build_training_frame
from .ingestion.batch import (
    DEFAULT_EVENTS,
    DEFAULT_JOURNEYS,
    DEFAULT_REPORT,
    DEFAULT_UNAVAILABLE,
    PROJECT_ROOT,
    _usable_sections,
    collect_batch,
)

DEFAULT_STATIONS = PROJECT_ROOT / "backend" / "data" / "stations_geocoded.csv"
DEFAULT_WEATHER_OUTPUT = PROJECT_ROOT / "backend" / "data" / "processed" / "historical_weather.csv"
DEFAULT_WEATHER_REPORT = PROJECT_ROOT / "backend" / "ml" / "data" / "historical_weather_report.json"


def _journey_section_stats(events_path: Path) -> tuple[int, int, float | None]:
    trains_path = PROJECT_ROOT / "backend" / "data" / "processed" / "trains.csv"
    stops_path = PROJECT_ROOT / "backend" / "data" / "processed" / "stops.csv"
    if not events_path.exists() or not trains_path.exists() or not stops_path.exists():
        return 0, 0, None
    try:
        import pandas as pd

        frame = build_training_frame(
            pd.read_csv(events_path),
            trains=pd.read_csv(trains_path),
            stops=pd.read_csv(stops_path),
        )
        journey_counts = frame.groupby(["train_number", "journey_date"], dropna=False).size()
        average = float(journey_counts.mean()) if len(journey_counts) else None
        return int(len(frame)), int(len(journey_counts)), average
    except Exception:
        return _usable_sections(events_path), 0, None


def _additional_journeys(usable_sections: int, average_sections: float | None) -> int | None:
    if usable_sections >= 100:
        return 0
    if not average_sections or average_sections <= 0:
        return None
    return max(1, math.ceil((100 - usable_sections) / average_sections))


def _run_post_collection(events_path: Path, usable_before: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "minimum_usable_sections": 100,
        "usable_sections_before_post_processing": usable_before,
        "weather": {"status": "not_run"},
        "database": {"status": "not_run"},
        "training": {"status": "not_run"},
    }
    if not events_path.exists():
        result["status"] = "deferred_no_event_file"
        result["reason"] = "No real RailKit running events are available."
        return result

    try:
        from .ingestion.weather import augment_events

        weather_report = augment_events(
            events_path,
            DEFAULT_STATIONS,
            DEFAULT_WEATHER_OUTPUT,
            DEFAULT_WEATHER_REPORT,
        )
        result["weather"] = {"status": "completed", "report": weather_report}
    except Exception as exc:
        result["weather"] = {"status": "failed", "error": str(exc)}

    try:
        from backend.scripts.build_database import main as build_database

        build_database()
        result["database"] = {"status": "completed"}
    except Exception as exc:
        result["database"] = {"status": "failed", "error": str(exc)}

    usable_after, journey_count, average_sections = _journey_section_stats(events_path)
    result["usable_sections_after_weather"] = usable_after
    result["journey_count"] = journey_count
    result["average_sections_per_successful_journey"] = average_sections
    result["approximately_additional_successful_journeys_needed"] = _additional_journeys(usable_after, average_sections)

    if usable_after < 100:
        result["status"] = "deferred_below_minimum"
        result["training"] = {
            "status": "deferred_below_minimum",
            "reason": "Training requires at least 100 real usable section rows.",
        }
        return result

    try:
        from .train import train_model

        training_report = train_model(events_path=events_path)
        result["status"] = "completed"
        result["training"] = {"status": "completed", "report": training_report}
    except Exception as exc:
        result["status"] = "training_failed"
        result["training"] = {"status": "failed", "error": str(exc)}
    return result


def run_pipeline(
    journeys_path: Path = DEFAULT_JOURNEYS,
    events_path: Path = DEFAULT_EVENTS,
    report_path: Path = DEFAULT_REPORT,
    unavailable_path: Path = DEFAULT_UNAVAILABLE,
) -> dict[str, Any]:
    collection = collect_batch(journeys_path, events_path, report_path, unavailable_path)
    usable_before = int(collection.get("usable_section_rows", 0) or 0)
    collection["post_processing"] = _run_post_collection(events_path, usable_before)
    collection["pipeline_completed_at"] = datetime.now(timezone.utc).isoformat()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(collection, indent=2, default=str) + "\n", encoding="utf-8")
    return collection


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RailETA collection, enrichment, database build, and gated training.")
    parser.add_argument("--journeys", type=Path, default=DEFAULT_JOURNEYS, help="CSV with confirmed train_number,journey_date pairs")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="Normalized running event CSV")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Collection and pipeline report JSON")
    parser.add_argument("--unavailable", type=Path, default=DEFAULT_UNAVAILABLE, help="Persistent no-history ledger")
    args = parser.parse_args()
    try:
        report = run_pipeline(args.journeys, args.events, args.report, args.unavailable)
    except DataUnavailableError as exc:
        print(str(exc))
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
