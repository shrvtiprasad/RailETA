"""
RailETA Phase 1 — build railway.db from backend/data/processed/*.csv.

Column names read here match railpull's real export.py output as processed
by process_timetable.py (see that file's docstring for the exact headers).

Refuses to run if processed/trains.csv or stations.csv is missing.
historical_delays.csv is optional; its absence is reported but does not
block train/station/stop loading.
"""
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.database import get_connection, init_schema  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BACKEND_DIR / "data" / "processed"

NTES_SOURCE_URL = "https://github.com/shwetankg07/railpull"


def load_csv(path: Path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    trains = load_csv(PROCESSED_DIR / "trains.csv")
    stations = load_csv(PROCESSED_DIR / "stations.csv")
    stops = load_csv(PROCESSED_DIR / "stops.csv")
    delays = load_csv(PROCESSED_DIR / "historical_delays.csv")

    if not trains or not stations:
        print("DATA SOURCE ACCESS REQUIRED")
        print("processed/trains.csv and processed/stations.csv must exist and be "
              "non-empty before building the database.")
        print("Run process_timetable.py first.")
        sys.exit(1)

    conn = get_connection()
    init_schema(conn)
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    for t in trains:
        cur.execute(
            """INSERT OR IGNORE INTO trains
               (train_number, train_name, train_type, source_station_code,
                destination_station_code, distance_km, runs_days,
                data_source, source_url, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                t.get("number"), t.get("name"), t.get("type"),
                t.get("source_code"), t.get("dest_code"),
                t.get("distance_km") or None, t.get("runs_days"),
                "NTES via railpull", NTES_SOURCE_URL, now,
            ),
        )

    for s in stations:
        lat, lon = s.get("lat"), s.get("lon")
        coord_source = "OpenStreetMap" if lat and lon else None
        cur.execute(
            """INSERT OR IGNORE INTO stations
               (station_code, station_name, state, zone, latitude, longitude,
                coordinate_source, data_source, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                s.get("code"), s.get("name"), None, None,
                float(lat) if lat else None, float(lon) if lon else None,
                coord_source, "railpull (+ OpenStreetMap geocode step)", now,
            ),
        )

    for st in stops:
        cur.execute(
            """INSERT INTO train_stops
               (train_number, station_code, sequence, day_offset,
                arrival_time, departure_time, halt_minutes, distance_from_source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                st.get("train_number"), st.get("station_code"),
                st.get("seq") or None, st.get("day") or None,
                st.get("arrival"), st.get("departure"),
                st.get("halt_min") or None, st.get("distance_km") or None,
            ),
        )

    for d in delays:
        cur.execute(
            """INSERT INTO historical_delays
               (train_number, station_code, average_delay_minutes,
                punctuality_percentage, delay_severity, scraped_at, source_url)
               VALUES (?,?,?,?,?,?,?)""",
            (
                d.get("train_number"), d.get("station_code"),
                d.get("average_delay_minutes"), d.get("punctuality_percentage"),
                d.get("delay_severity"), d.get("scraped_at"), d.get("source_url"),
            ),
        )

    conn.commit()
    print(f"Loaded {len(trains)} trains, {len(stations)} stations, "
          f"{len(stops)} stops, {len(delays)} historical delay rows.")
    if not any(s.get("lat") for s in stations):
        print("NOTE: no station coordinates loaded -- run railpull's OSM geocode "
              "step (npm install && node osm/geocode_stations.mjs <extract>.pbf) "
              "and re-export if you need lat/lon.")
    if not delays:
        print("NOTE: no historical_delays rows loaded -- run process_delays.py "
              "with the manually-downloaded Kaggle CSV first.")
    conn.close()


if __name__ == "__main__":
    main()
