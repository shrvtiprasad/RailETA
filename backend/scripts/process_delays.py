"""
RailETA Phase 1 — process the ETrain.info-derived Kaggle historical delay
dataset into processed/historical_delays.csv.

Kaggle requires authentication to download, which must be done manually.
Place the extracted CSV(s) into backend/data/raw/delays/. If nothing is
found there, this script stops and prints DATA SOURCE ACCESS REQUIRED
rather than generating placeholder rows.
"""
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DELAYS_DIR = BACKEND_DIR / "data" / "raw" / "delays"
OUT_DIR = BACKEND_DIR / "data" / "processed"

SOURCE_URL = "https://www.kaggle.com/datasets/naijilaji/indian-railways-passenger-train-delays-dataset"

COLUMN_MAP_CANDIDATES = {
    "train_number": ["train_number", "Train_No", "train_no", "TrainNumber"],
    "station_code": ["station_code", "Station_Code", "station"],
    "average_delay_minutes": ["average_delay_minutes", "avg_delay", "Average_Delay"],
    "punctuality_percentage": ["punctuality_percentage", "punctuality", "Punctuality_%"],
    "delay_severity": ["delay_severity", "severity"],
    "scraped_at": ["scraped_at", "scrape_date", "date"],
}


def find_csv_files():
    if not RAW_DELAYS_DIR.exists():
        return []
    return list(RAW_DELAYS_DIR.glob("*.csv"))


def map_row(row: dict) -> dict:
    out = {"source_url": SOURCE_URL}
    for target, candidates in COLUMN_MAP_CANDIDATES.items():
        for c in candidates:
            if c in row and row[c] not in (None, ""):
                out[target] = row[c]
                break
        else:
            out[target] = None
    return out


def main():
    csv_files = find_csv_files()
    if not csv_files:
        print("DATA SOURCE ACCESS REQUIRED")
        print("Kaggle requires authentication; download manually from:")
        print(f"  {SOURCE_URL}")
        print(f"and place the extracted CSV(s) into:\n  {RAW_DELAYS_DIR}")
        sys.exit(1)

    all_rows = []
    for path in csv_files:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            print(f"{path.name} columns found: {reader.fieldnames}")
            for row in reader:
                all_rows.append(map_row(row))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "historical_delays.csv"
    fieldnames = ["train_number", "station_code", "average_delay_minutes",
                  "punctuality_percentage", "delay_severity", "scraped_at", "source_url"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(all_rows)} historical delay rows to {out_path}")
    print(f"Processed at: {datetime.now(timezone.utc).isoformat()}")
    print("NOTE: verify COLUMN_MAP_CANDIDATES against the actual downloaded "
          "CSV header -- it could not be inspected from this sandbox.")


if __name__ == "__main__":
    main()
