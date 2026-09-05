import sqlite3
from datetime import datetime, timezone

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.api.services.railradar import RailRadarError, fetch_live_train

router = APIRouter(prefix="/trains", tags=["Trains"])

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "railway.db"

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _live_summary(payload: dict) -> dict:
    data = payload.get("data", payload) if isinstance(payload.get("data", payload), dict) else {}
    location = data.get("currentLocation") if isinstance(data.get("currentLocation"), dict) else {}
    train = data.get("train") if isinstance(data.get("train"), dict) else {}
    route = data.get("route") if isinstance(data.get("route"), list) else []
    current_code = location.get("stationCode") or location.get("station_code")
    current_name = location.get("stationName") or location.get("station_name")
    if current_code and not current_name:
        match = next(
            (stop for stop in route if isinstance(stop, dict) and (stop.get("stationCode") or stop.get("station_code")) == current_code),
            None,
        )
        current_name = match.get("stationName") or match.get("station_name") if match else None
    return {
        "train_number": str(data.get("trainNumber") or train.get("number") or ""),
        "status": data.get("status") or data.get("trainStatus") or location.get("status"),
        "current_station": {"code": current_code, "name": current_name} if current_code else None,
        "current_delay_minutes": data.get("delayMinutes") if data.get("delayMinutes") is not None else data.get("currentDelayMinutes"),
        "updated_at": data.get("updatedAt") or data.get("lastUpdated") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("")
def get_trains():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                train_number,
                train_name,
                train_type,
                source_station_code,
                destination_station_code,
                distance_km,
                runs_days
            FROM trains
            ORDER BY train_number
            """
        ).fetchall()

        return {
            "count": len(rows),
            "trains": [dict(row) for row in rows],
        }

    finally:
        connection.close()


@router.get("/{train_number}/live")
async def get_live_train(train_number: str):
    """
    Get live train data directly from RailRadar.

    This endpoint intentionally does NOT check SQLite first.
    Therefore, a train can be displayed on the live map even if
    it is not present in railway.db.
    """

    try:
        payload = await fetch_live_train(train_number)
        return {**payload, **_live_summary(payload)}
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/{train_number}")
def get_train(train_number: str):
    connection = get_connection()

    try:
        train = connection.execute(
            """
            SELECT
                train_number,
                train_name,
                train_type,
                source_station_code,
                destination_station_code,
                distance_km,
                runs_days
            FROM trains
            WHERE train_number = ?
            """,
            (train_number,),
        ).fetchone()

        if train is None:
            raise HTTPException(
                status_code=404,
                detail=f"Train {train_number} not found",
            )

        stops = connection.execute(
            """
            SELECT
                station_code,
                sequence,
                day_offset,
                arrival_time,
                departure_time,
                halt_minutes,
                distance_from_source
            FROM train_stops
            WHERE train_number = ?
            ORDER BY sequence
            """,
            (train_number,),
        ).fetchall()

        return {
            "train": dict(train),
            "stops": [dict(stop) for stop in stops],
        }

    finally:
        connection.close()
