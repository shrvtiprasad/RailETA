from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .railkit import RailKitHistoryClient, normalize_history

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements install supplies this
    load_dotenv = None  # type: ignore[assignment]


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def run_coverage(trains_file: Path, dates_file: Path, output: Path) -> dict:
    trains = _lines(trains_file)
    dates = _lines(dates_file)
    if not trains or not dates:
        raise ValueError("Coverage files must contain at least one train and one completed journey date.")
    if load_dotenv is not None:
        load_dotenv(_root() / "backend" / ".env")
    client = RailKitHistoryClient()
    results = []
    successful_journeys = 0
    station_events = 0
    for train in trains:
        for journey_date in dates:
            result = {"train_number": train, "journey_date": journey_date, "status": "unavailable"}
            try:
                payload = client.fetch_history(train, journey_date)
                rows = normalize_history(payload, train, journey_date)
                if rows:
                    successful_journeys += 1
                    station_events += len(rows)
                    result.update({"status": "success", "station_events": len(rows)})
                else:
                    result["status"] = "empty"
            except Exception as exc:
                result["error"] = str(exc)
            results.append(result)
    attempted = len(results)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requests_attempted": attempted,
        "successful_journeys": successful_journeys,
        "unavailable_or_empty_journeys": attempted - successful_journeys,
        "coverage_percentage": round(successful_journeys / attempted * 100, 2) if attempted else 0.0,
        "train_count": len(trains),
        "date_count": len(dates),
        "unique_station_events": station_events,
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    root = _root()
    parser = argparse.ArgumentParser(description="Run a controlled RailKit history coverage study.")
    parser.add_argument("--trains-file", type=Path, required=True, help="One train number per line")
    parser.add_argument("--dates-file", type=Path, required=True, help="One completed journey date per line")
    parser.add_argument("--output", type=Path, default=root / "backend" / "ml" / "data" / "historical_data_report.json")
    args = parser.parse_args()
    print(json.dumps(run_coverage(args.trains_file, args.dates_file, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
