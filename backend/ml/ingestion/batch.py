from __future__ import annotations

import argparse
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..contract import DataUnavailableError
from ..features import build_training_frame
from ..railkit import RailKitHistoryClient, merge_events, normalize_history

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    load_dotenv = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_JOURNEYS = PROJECT_ROOT / "journeys.csv"
DEFAULT_EVENTS = PROJECT_ROOT / "backend" / "data" / "processed" / "running_events.csv"
DEFAULT_REPORT = PROJECT_ROOT / "backend" / "ml" / "data" / "historical_data_collection_report.json"
DEFAULT_UNAVAILABLE = PROJECT_ROOT / "backend" / "ml" / "data" / "railkit_unavailable.csv"


def _read_nonnegative_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return max(0, int(value))
    except ValueError as exc:
        raise DataUnavailableError(f"{name} must be a non-negative integer.") from exc


def _load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / "backend" / ".env", override=False)


def _read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        # Historical RailKit collection is opt-in.  The normal pipeline must
        # still be able to process the real data already present in the
        # repository when no confirmed history manifest exists.  In
        # particular, do not turn the absence of a manifest into a request to
        # guess dates or into a hard failure that blocks weather/database
        # processing.
        print(
            f"No optional RailKit journey manifest found at {path}; "
            "skipping historical API collection and using existing local artifacts."
        )
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        content = "\n".join(
            line for line in handle.read().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(io.StringIO(content))
        required = {"train_number", "journey_date"}
        fields = set(reader.fieldnames or [])
        if not required.issubset(fields):
            missing = ", ".join(sorted(required - fields))
            raise DataUnavailableError(f"journeys.csv is missing required columns: {missing}.")
        manifest: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            first_value = str(next(iter(row.values()), "") or "").strip()
            if first_value.startswith("#"):
                continue
            train = str(row.get("train_number") or "").strip()
            journey_date = str(row.get("journey_date") or "").strip()
            if not train and not journey_date:
                continue
            if not train or not journey_date:
                manifest.append({"_invalid": f"line {line_number}: both train_number and journey_date are required"})
                continue
            manifest.append({"train_number": train, "journey_date": journey_date})
    return manifest


def _status_for_error(error: Exception) -> str:
    message = str(error).lower()
    if "not found" in message or "no history" in message or "record not found" in message:
        return "unavailable"
    return "failed"


def _canonical_date(value: str) -> str:
    for pattern in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return value.strip()


def _read_unavailable(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            (str(row.get("train_number") or "").strip(), _canonical_date(str(row.get("journey_date") or "")))
            for row in csv.DictReader(handle)
            if row.get("train_number") and row.get("journey_date")
        }


def _record_unavailable(path: Path, train: str, journey_date: str, reason: str) -> None:
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
    key = (train, _canonical_date(journey_date))
    if any((row.get("train_number", ""), _canonical_date(row.get("journey_date", ""))) == key for row in existing):
        return
    existing.append({
        "train_number": train,
        "journey_date": journey_date,
        "reason": reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["train_number", "journey_date", "reason", "recorded_at"])
        writer.writeheader()
        writer.writerows(existing)
    temporary.replace(path)


def _usable_sections(events_path: Path) -> int:
    trains_path = PROJECT_ROOT / "backend" / "data" / "processed" / "trains.csv"
    stops_path = PROJECT_ROOT / "backend" / "data" / "processed" / "stops.csv"
    if not events_path.exists() or not trains_path.exists() or not stops_path.exists():
        return 0
    try:
        import pandas as pd

        events = pd.read_csv(events_path)
        trains = pd.read_csv(trains_path)
        stops = pd.read_csv(stops_path)
        return int(len(build_training_frame(events, trains=trains, stops=stops)))
    except Exception:
        return 0


def collect_batch(
    journeys_path: Path = DEFAULT_JOURNEYS,
    events_path: Path = DEFAULT_EVENTS,
    report_path: Path = DEFAULT_REPORT,
    unavailable_path: Path = DEFAULT_UNAVAILABLE,
) -> dict[str, Any]:
    _load_environment()
    manifest = _read_manifest(journeys_path)
    client = RailKitHistoryClient()
    unavailable = _read_unavailable(unavailable_path)
    safety_buffer = _read_nonnegative_env("RAILKIT_SAFETY_BUFFER_REQUESTS", 1)
    quota_before = client.quota_status()
    safe_remaining_before = max(0, int(quota_before["remaining"] or 0) - safety_buffer)
    print(
        "RailKit budget before collection: "
        f"configured_limit={quota_before['limit']}, "
        f"locally_recorded_usage={quota_before['locally_recorded_usage']}, "
        f"effective_used={quota_before['used']}, "
        f"estimated_remaining={quota_before['remaining']}, "
        f"safety_buffer={safety_buffer}, safe_new_requests={safe_remaining_before}"
    )
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    safety_stop = False

    for item in manifest:
        if "_invalid" in item:
            results.append({"status": "failed", "error": item["_invalid"]})
            continue
        train = item["train_number"]
        journey_date = item["journey_date"]
        key = (train, journey_date)
        if key in seen:
            results.append({"train_number": train, "journey_date": journey_date, "status": "skipped_duplicate_manifest"})
            continue
        seen.add(key)

        canonical_key = (train, _canonical_date(journey_date))
        if canonical_key in unavailable:
            results.append({"train_number": train, "journey_date": journey_date, "status": "skipped_unavailable_record"})
            continue

        try:
            cached = client.is_cached(train, journey_date)
            if not cached:
                quota = client.quota_status()
                safe_remaining = max(0, int(quota["remaining"] or 0) - safety_buffer)
                if safety_stop or safe_remaining <= 0:
                    results.append({
                        "train_number": train,
                        "journey_date": journey_date,
                        "status": "skipped_safety_buffer",
                        "quota": quota,
                    })
                    safety_stop = True
                    continue
            payload = client.fetch_history(train, journey_date, force=False)
            records = normalize_history(payload, train, journey_date)
            if not records:
                _record_unavailable(unavailable_path, train, journey_date, "Train history record not found")
                unavailable.add(canonical_key)
                results.append({"train_number": train, "journey_date": journey_date, "status": "unavailable", "station_events": 0})
                continue
            merge_events(events_path, records)
            results.append({
                "train_number": train,
                "journey_date": journey_date,
                "status": "skipped_cached" if cached else "successful",
                "station_events": len(records),
                "events_appended_without_duplicates": True,
            })
        except Exception as exc:
            status = _status_for_error(exc)
            if status == "unavailable":
                _record_unavailable(unavailable_path, train, journey_date, str(exc))
                unavailable.add(canonical_key)
            results.append({
                "train_number": train,
                "journey_date": journey_date,
                "status": status,
                "error": str(exc),
            })

    usable_sections = _usable_sections(events_path)
    quota_after = client.quota_status()
    counts = {
        status: sum(1 for result in results if result.get("status") == status)
        for status in ("successful", "unavailable", "failed", "skipped_cached", "skipped_unavailable_record", "skipped_duplicate_manifest", "skipped_safety_buffer")
    }
    counts["skipped"] = sum(value for key, value in counts.items() if key.startswith("skipped_"))
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "RailKit Train History API",
        "journeys_file": str(journeys_path),
        "events_file": str(events_path),
        "requested_pairs": len(manifest),
        "historical_collection": {
            "mode": "explicit_manifest_only",
            "manifest_present": journeys_path.exists(),
            "railkit_calls_made": max(0, int(quota_after["used"] or 0) - int(quota_before["used"] or 0)),
            "note": (
                "Only confirmed train/date pairs from the optional manifest are eligible for RailKit. "
                "No dates or journeys are inferred from timetable data."
            ),
        },
        "unique_pairs_processed": len(seen),
        "counts": counts,
        "station_events_from_successful_or_cached": sum(int(result.get("station_events", 0) or 0) for result in results),
        "usable_section_rows": usable_sections,
        "safety_buffer_requests": safety_buffer,
        "minimum_usable_sections": 100,
        "collection_stopped_at_safety_buffer": safety_stop,
        "unavailable_ledger": str(unavailable_path),
        "quota_before": quota_before,
        "quota_after": quota_after,
        "results": results,
        "post_processing": {"status": "not_run_by_collector"},
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect confirmed RailKit journeys with cache and quota protection.")
    parser.add_argument("--journeys", type=Path, default=DEFAULT_JOURNEYS, help="CSV with train_number,journey_date")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="Normalized running event CSV")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Collection report JSON")
    parser.add_argument("--unavailable", type=Path, default=DEFAULT_UNAVAILABLE, help="Persistent no-history ledger")
    args = parser.parse_args()
    try:
        report = collect_batch(args.journeys, args.events, args.report, args.unavailable)
    except DataUnavailableError as exc:
        print(str(exc))
        return 2
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
