"""
RailETA Phase 1 — Step 2: select a representative 100-300 train subset
from railpull's raw export, and normalize into processed/ CSVs.

Column names below match railpull's transform/export.py EXACTLY (verified by
reading that file):

  trains.csv:   number,name,type,type_label,runs_days,source_code,source,
                dest_code,destination,distance_km,travel_time,num_stops
  stops.csv:    train_number,seq,station_code,station_name,day,arrival,
                departure,halt_min,distance_km
  stations.csv: code,name,lat,lon   (lat/lon blank unless OSM geocode step ran)

Refuses to run (prints DATA SOURCE ACCESS REQUIRED) if raw files are absent.
Never invents trains, stations, or coordinates. If fewer than 100 usable
trains are available after filtering, uses exactly what's available and
reports the real number.
"""
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BACKEND_DIR / "data" / "raw" / "ntes"
OUT_DIR = BACKEND_DIR / "data" / "processed"

TARGET_MIN, TARGET_MAX = 100, 300

# NTES type codes, per railpull's TYPE_LABEL map, matching the project's
# preferred categories (Vande Bharat / Rajdhani / Shatabdi / Duronto /
# Superfast / Express).
PREFERRED_TYPES = {"VNDB", "VNDM", "VNDS", "RAJ", "SHT", "JSH", "DRNT", "SUF", "MEX", "EXP"}

REQUIRED_RAW = ["trains.csv", "stops.csv", "stations.csv"]


def fail_missing_source():
    print("DATA SOURCE ACCESS REQUIRED")
    print(f"Expected railpull export files in: {RAW_DIR}")
    print("Missing one or more of:", ", ".join(REQUIRED_RAW))
    print("Run backend/scripts/fetch_timetable.py for exact instructions.")
    sys.exit(1)


def load_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def zone_proxy(train_number: str) -> str:
    """First digit of the train number as a coarse zone-spread proxy for
    SELECTION ONLY (to avoid picking 300 trains that are all numerically
    adjacent). This is not stored as a `zone` value anywhere and is never
    written to the database -- real zone data isn't in this source (see
    models.py docstring)."""
    return train_number[0] if train_number else "?"


def main():
    if not all((RAW_DIR / f).exists() for f in REQUIRED_RAW):
        fail_missing_source()

    trains = load_csv(RAW_DIR / "trains.csv")
    stops = load_csv(RAW_DIR / "stops.csv")
    stations = load_csv(RAW_DIR / "stations.csv")

    if not trains:
        print("DATA SOURCE ACCESS REQUIRED")
        print(f"{RAW_DIR / 'trains.csv'} exists but contains zero rows.")
        sys.exit(1)

    preferred = [t for t in trains if t.get("type", "").strip().upper() in PREFERRED_TYPES]
    rest = [t for t in trains if t not in preferred]

    # Spread the selection across first-digit "buckets" as a real-data-only
    # proxy for geographic/zonal diversity (train numbering blocks are not
    # random), rather than just taking the first N rows in file order.
    from collections import defaultdict
    buckets = defaultdict(list)
    for t in preferred:
        buckets[zone_proxy(t["number"])].append(t)

    selected = []
    idx = 0
    bucket_keys = sorted(buckets.keys())
    while len(selected) < TARGET_MAX and any(buckets[k] for k in bucket_keys):
        for k in bucket_keys:
            if buckets[k]:
                selected.append(buckets[k].pop(0))
            if len(selected) >= TARGET_MAX:
                break
        idx += 1
        if idx > 2000:  # safety valve, not a data limit
            break

    if len(selected) < TARGET_MIN:
        remaining = [t for t in rest if t not in selected]
        selected += remaining[: (TARGET_MIN - len(selected))]

    selected = selected[:TARGET_MAX]
    selected_numbers = {t["number"] for t in selected}

    selected_stops = [s for s in stops if s.get("train_number") in selected_numbers]
    stop_station_codes = {s["station_code"] for s in selected_stops}
    selected_stations = [st for st in stations if st.get("code") in stop_station_codes]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    def write_csv(path, rows, fieldnames):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    if selected:
        write_csv(OUT_DIR / "trains.csv", selected, list(selected[0].keys()))
    if selected_stops:
        write_csv(OUT_DIR / "stops.csv", selected_stops, list(selected_stops[0].keys()))
    if selected_stations:
        write_csv(OUT_DIR / "stations.csv", selected_stations, list(selected_stations[0].keys()))

    type_counts = {}
    for t in selected:
        ty = t.get("type_label", t.get("type", "Unknown"))
        type_counts[ty] = type_counts.get(ty, 0) + 1

    print(f"Selected {len(selected)} real trains (source had {len(trains)} total).")
    print(f"Type breakdown: {type_counts}")
    print(f"Selected {len(selected_stations)} real stations referenced by those trains.")
    print(f"Selected {len(selected_stops)} real stop records.")
    print(f"Processed at: {now}")
    if len(selected) < TARGET_MIN:
        print(f"NOTE: fewer than {TARGET_MIN} usable trains were available "
              f"in the source after filtering. Using the real number: {len(selected)}. "
              f"No synthetic trains were added.")


if __name__ == "__main__":
    main()
