"""
RailETA Phase 1 — validate railway.db and write validation_report.json.
Only ever reports problems; never fabricates fixes.
"""
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.database import get_connection  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPORT_PATH = BACKEND_DIR / "data" / "validation_report.json"


def parseable_time(t):
    if not t:
        return True
    parts = t.strip().split(":")
    if len(parts) != 2:
        return False
    try:
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 47 and 0 <= m < 60
    except ValueError:
        return False


def main():
    db_path = BACKEND_DIR / "data" / "railway.db"
    if not db_path.exists():
        print("DATA SOURCE ACCESS REQUIRED")
        print(f"{db_path} does not exist. Run build_database.py first.")
        sys.exit(1)

    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    trains = cur.execute("SELECT * FROM trains").fetchall()
    stations = cur.execute("SELECT * FROM stations").fetchall()
    stops = cur.execute("SELECT * FROM train_stops").fetchall()
    delays = cur.execute("SELECT * FROM historical_delays").fetchall()

    train_numbers = {t["train_number"] for t in trains}
    station_codes = {s["station_code"] for s in stations}

    stops_bad_train = [s["train_number"] for s in stops if s["train_number"] not in train_numbers]
    stops_bad_station = [s["station_code"] for s in stops if s["station_code"] not in station_codes]

    unmatched_delay_trains = sorted({d["train_number"] for d in delays
                                      if d["train_number"] and d["train_number"] not in train_numbers})
    unmatched_delay_stations = sorted({d["station_code"] for d in delays
                                        if d["station_code"] and d["station_code"] not in station_codes})

    missing_coords = [s["station_code"] for s in stations
                       if s["latitude"] is None or s["longitude"] is None]
    invalid_coords = [s["station_code"] for s in stations
                       if s["latitude"] is not None and not (-90 <= s["latitude"] <= 90)
                       or s["longitude"] is not None and not (-180 <= s["longitude"] <= 180)]

    unordered_trains = []
    by_train = {}
    for s in stops:
        by_train.setdefault(s["train_number"], []).append(s["sequence"])
    for tn, seqs in by_train.items():
        seqs_clean = [x for x in seqs if x is not None]
        if seqs_clean != sorted(seqs_clean):
            unordered_trains.append(tn)

    bad_times = [(s["train_number"], s["station_code"]) for s in stops
                 if not parseable_time(s["arrival_time"]) or not parseable_time(s["departure_time"])]

    dup_trains = len(trains) - len(train_numbers)
    dup_stations = len(stations) - len(station_codes)

    trains_missing_provenance = [t["train_number"] for t in trains if not t["data_source"] or not t["collected_at"]]
    stations_missing_provenance = [s["station_code"] for s in stations if not s["data_source"] or not s["collected_at"]]

    missing_schedule_fields = [(s["train_number"], s["station_code"]) for s in stops if s["sequence"] is None]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "trains": len(trains), "stations": len(stations),
            "train_stops": len(stops), "historical_delays": len(delays),
        },
        "unmatched_train_numbers_in_stops": sorted(set(stops_bad_train)),
        "unmatched_station_codes_in_stops": sorted(set(stops_bad_station)),
        "unmatched_train_numbers_in_delays": unmatched_delay_trains,
        "unmatched_station_codes_in_delays": unmatched_delay_stations,
        "missing_coordinates": sorted(missing_coords),
        "invalid_coordinates": sorted(invalid_coords),
        "trains_with_unordered_stop_sequence": unordered_trains,
        "unparseable_times": bad_times,
        "duplicate_train_records": dup_trains,
        "duplicate_station_records": dup_stations,
        "trains_missing_provenance": trains_missing_provenance,
        "stations_missing_provenance": stations_missing_provenance,
        "stops_missing_sequence": missing_schedule_fields,
        "sources": {
            "timetable": {"source": "NTES", "extraction": "railpull", "url": "https://github.com/shwetankg07/railpull"},
            "coordinates": {"sources": ["OpenStreetMap (optional railpull geocode step)"]},
            "historical_delays": {
                "source": "ETrain.info-derived Kaggle dataset",
                "url": "https://www.kaggle.com/datasets/naijilaji/indian-railways-passenger-train-delays-dataset",
            },
        },
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Validation report written to {REPORT_PATH}")
    print(json.dumps(report["counts"], indent=2))
    conn.close()


if __name__ == "__main__":
    main()
