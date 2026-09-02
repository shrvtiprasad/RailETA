"""
RailETA Phase 1 — Step 1 guard: confirms railpull's real NTES export exists
before any processing runs. The actual extraction happens outside this
sandbox (see the Windows procedure your operator gave you separately).

Refuses silently faking data: prints DATA SOURCE ACCESS REQUIRED and exits
non-zero if backend/data/raw/ntes/{trains,stops,stations}.csv and
schedules.jsonl are not all present.
"""
import sys
from pathlib import Path

RAW_NTES_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "ntes"
REQUIRED_FILES = ["trains.csv", "stops.csv", "stations.csv", "schedules.jsonl"]


def check_raw_data_present() -> bool:
    missing = [f for f in REQUIRED_FILES if not (RAW_NTES_DIR / f).exists()]
    if missing:
        print("DATA SOURCE ACCESS REQUIRED")
        print(f"Missing files in {RAW_NTES_DIR}:")
        for f in missing:
            print(f"  - {f}")
        print()
        print("Run railpull on a machine with normal internet access, then copy")
        print(f"trains.csv, stops.csv, stations.csv, schedules.jsonl into:\n  {RAW_NTES_DIR}")
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if check_raw_data_present() else 1)
