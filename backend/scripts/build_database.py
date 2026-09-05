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
    geocoded_stations = load_csv(PROCESSED_DIR / "stations_geocoded.csv")
    if not geocoded_stations:
        geocoded_stations = load_csv(BACKEND_DIR / "data" / "stations_geocoded.csv")
    stops = load_csv(PROCESSED_DIR / "stops.csv")
    delays = load_csv(PROCESSED_DIR / "historical_delays.csv")
    running_events = load_csv(PROCESSED_DIR / "running_events.csv")
    historical_weather = load_csv(PROCESSED_DIR / "historical_weather.csv")

    if not trains or not stations:
        print("DATA SOURCE ACCESS REQUIRED")
        print("processed/trains.csv and processed/stations.csv must exist and be "
              "non-empty before building the database.")
        print("Run process_timetable.py first.")
        sys.exit(1)

    # Keep the canonical station table, but fill missing coordinates from the
    # existing geocoder export so the map can use real station geometry.
    geocoded_by_code = {
        str(row.get("code") or row.get("station_code") or "").strip(): row
        for row in geocoded_stations
    }
    for station in stations:
        code = str(station.get("code") or station.get("station_code") or "").strip()
        match = geocoded_by_code.get(code)
        if not match:
            continue
        if not station.get("lat") and match.get("lat"):
            station["lat"] = match["lat"]
        if not station.get("lon") and match.get("lon"):
            station["lon"] = match["lon"]

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
        cur.execute(
            """UPDATE stations
               SET station_name = COALESCE(?, station_name),
                   latitude = COALESCE(?, latitude),
                   longitude = COALESCE(?, longitude),
                   coordinate_source = COALESCE(?, coordinate_source),
                   data_source = COALESCE(?, data_source),
                   collected_at = COALESCE(?, collected_at)
               WHERE station_code = ?""",
            (
                s.get("name"),
                float(lat) if lat else None,
                float(lon) if lon else None,
                coord_source,
                "railpull (+ OpenStreetMap geocode step)",
                now,
                s.get("code"),
            ),
        )

    for st in stops:
        cur.execute(
            """INSERT INTO train_stops
               (train_number, station_code, sequence, day_offset,
                arrival_time, departure_time, halt_minutes, distance_from_source)
               SELECT ?,?,?,?,?,?,?,?
               WHERE NOT EXISTS (
                   SELECT 1 FROM train_stops
                   WHERE train_number = ? AND station_code = ? AND sequence = ?
               )""",
            (
                st.get("train_number"), st.get("station_code"),
                st.get("seq") or None, st.get("day") or None,
                st.get("arrival"), st.get("departure"),
                st.get("halt_min") or None, st.get("distance_km") or None,
                st.get("train_number"), st.get("station_code"), st.get("seq") or None,
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

    journey_ids = {}
    for event in running_events:
        train_number = (event.get("train_number") or "").strip()
        journey_date = (event.get("journey_date") or "").strip()
        if not train_number or not journey_date:
            continue
        key = (train_number, journey_date)
        cur.execute(
            """INSERT OR IGNORE INTO historical_journeys
               (train_number, journey_date, train_name, train_type,
                source_station_code, destination_station_code, data_source,
                collected_at, raw_cache_path)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                train_number,
                journey_date,
                event.get("train_name"),
                event.get("train_type"),
                event.get("source_station_code"),
                event.get("destination_station_code"),
                event.get("data_source") or "RailKit Train History API",
                event.get("collected_at") or now,
                event.get("raw_cache_path"),
            ),
        )
        journey_ids[key] = cur.execute(
            "SELECT id FROM historical_journeys WHERE train_number = ? AND journey_date = ?",
            key,
        ).fetchone()[0]

    for event in running_events:
        train_number = (event.get("train_number") or "").strip()
        journey_date = (event.get("journey_date") or "").strip()
        station_code = (event.get("station_code") or "").strip()
        if not train_number or not journey_date or not station_code:
            continue
        journey_id = journey_ids.get((train_number, journey_date))
        if journey_id is None:
            continue
        cur.execute(
            """INSERT INTO running_events
               (journey_id, train_number, journey_date, station_code,
                station_name, station_sequence, distance_from_origin,
                scheduled_arrival, actual_arrival, arrival_delay_minutes,
                scheduled_departure, actual_departure, departure_delay_minutes,
                platform, data_source, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(train_number, journey_date, station_code, station_sequence)
               DO UPDATE SET
                 journey_id=excluded.journey_id,
                 station_name=excluded.station_name,
                 distance_from_origin=excluded.distance_from_origin,
                 scheduled_arrival=excluded.scheduled_arrival,
                 actual_arrival=excluded.actual_arrival,
                 arrival_delay_minutes=excluded.arrival_delay_minutes,
                 scheduled_departure=excluded.scheduled_departure,
                 actual_departure=excluded.actual_departure,
                 departure_delay_minutes=excluded.departure_delay_minutes,
                 platform=excluded.platform,
                 data_source=excluded.data_source,
                 collected_at=excluded.collected_at""",
            (
                journey_id,
                train_number,
                journey_date,
                station_code,
                event.get("station_name"),
                event.get("sequence") or 0,
                event.get("distance_from_origin") or None,
                event.get("scheduled_arrival") or None,
                event.get("actual_arrival") or None,
                event.get("arrival_delay_minutes") or None,
                event.get("scheduled_departure") or None,
                event.get("actual_departure") or None,
                event.get("departure_delay_minutes") or None,
                event.get("platform") or None,
                event.get("data_source") or "RailKit Train History API",
                event.get("collected_at") or now,
            ),
        )

    for weather in historical_weather:
        if not weather.get("timestamp") or not weather.get("latitude") or not weather.get("longitude"):
            continue
        cur.execute(
            """INSERT OR IGNORE INTO historical_weather
               (timestamp, latitude, longitude, station_code,
                temperature_2m, relative_humidity_2m, precipitation, rain,
                wind_speed_10m, weather_code, data_source, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                weather.get("timestamp"),
                weather.get("latitude"),
                weather.get("longitude"),
                weather.get("station_code") or None,
                weather.get("temperature_2m") or None,
                weather.get("relative_humidity_2m") or None,
                weather.get("precipitation") or None,
                weather.get("rain") or None,
                weather.get("wind_speed_10m") or None,
                weather.get("weather_code") or None,
                weather.get("source") or "Open-Meteo Historical Weather API",
                weather.get("collected_at") or now,
            ),
        )

    conn.commit()
    print(f"Loaded {len(trains)} trains, {len(stations)} stations, "
          f"{len(stops)} stops, {len(delays)} historical delay rows, "
          f"{len(running_events)} running events, {len(historical_weather)} weather rows.")
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
