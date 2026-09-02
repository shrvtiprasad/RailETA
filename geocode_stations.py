import csv
import sqlite3
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "backend" / "data" / "railway.db"
CSV_PATH = BASE_DIR / "backend" / "data" / "stations_geocoded.csv"
FAILED_PATH = BASE_DIR / "backend" / "data" / "geocode_failed.csv"

URL = "https://nominatim.openstreetmap.org/search"

HEADERS = {
    "User-Agent": "RailETA/1.0 (SIH railway ETA prediction prototype)"
}

session = requests.Session()
session.headers.update(HEADERS)


def geocode_station(code, name):
    queries = [
        f"{name} railway station, India",
        f"{name}, India",
    ]

    for query in queries:
        fallback = None

        try:
            response = session.get(
                URL,
                params={
                    "q": query,
                    "format": "json",
                    "limit": 1,
                },
                timeout=20,
            )

            response.raise_for_status()
            results = response.json()

            if results:
                result = results[0]

                lat = result.get("lat")
                lon = result.get("lon")

                if lat and lon:
                    return lat, lon

        except requests.RequestException as e:
            print(f"  Request error: {e}")

        time.sleep(2)

    return None, None

def main():
    conn = sqlite3.connect(DB_PATH)

    stations = conn.execute("""
        SELECT station_code, station_name, latitude, longitude
        FROM stations
        ORDER BY station_code
    """).fetchall()

    print(f"Stations in database: {len(stations)}")

    results = []
    failed = []

    for i, (code, name, lat, lon) in enumerate(stations, start=1):

        print(f"[{i}/{len(stations)}] {code} - {name}")

        # Already has coordinates
        if lat is not None and lon is not None:
            results.append((code, name, lat, lon))
            print(f"  Existing: {lat}, {lon}")
            continue

        new_lat, new_lon = geocode_station(code, name)

        if new_lat and new_lon:
            results.append((code, name, float(new_lat), float(new_lon)))

            conn.execute("""
                UPDATE stations
                SET latitude = ?,
                    longitude = ?,
                    coordinate_source = 'Nominatim / OpenStreetMap'
                WHERE station_code = ?
            """, (float(new_lat), float(new_lon), code))

            conn.commit()

            print(f"  ✓ {new_lat}, {new_lon}")

        else:
            results.append((code, name, None, None))
            failed.append((code, name))
            print("  ✗ Not found")

        # Nominatim-friendly pacing
        time.sleep(1.2)

        # Save progress periodically
        if i % 25 == 0:
            save_csv(results)
            save_failed(failed)
            print("  Progress saved.")

    save_csv(results)
    save_failed(failed)

    conn.close()

    successful = sum(
        1 for _, _, lat, lon in results
        if lat is not None and lon is not None
    )

    print()
    print("==============================")
    print("GEOCODING COMPLETE")
    print("==============================")
    print(f"Total stations : {len(stations)}")
    print(f"With coordinates: {successful}")
    print(f"Failed          : {len(failed)}")
    print(f"Database        : {DB_PATH}")


def save_csv(rows):
    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name", "lat", "lon"])
        writer.writerows(rows)


def save_failed(rows):
    with FAILED_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["code", "name"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()