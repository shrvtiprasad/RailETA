import os
import sqlite3

from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException


load_dotenv()

router = APIRouter(prefix="/trains", tags=["Trains"])

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "railway.db"

RAILRADAR_API_URL = "https://api.railradar.in/v1/trains"


def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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

    api_key = os.getenv("RAILRADAR_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="RAILRADAR_API_KEY is not configured",
        )

    url = (
        f"{RAILRADAR_API_URL}/{train_number}/live"
        "?geometry=true&format=geojson&includeCoordinates=true"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            verify=True,
        ) as client:
            response = await client.get(
                url,
                headers=headers,
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="RailRadar request timed out",
        )

    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to RailRadar: {error}",
        )

    if response.status_code == 401:
        raise HTTPException(
            status_code=502,
            detail="RailRadar API authentication failed",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Live data for train {train_number} was not found on RailRadar",
        )

    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="RailRadar API request limit reached",
        )

    if response.status_code >= 500:
        raise HTTPException(
            status_code=502,
            detail="RailRadar live service is temporarily unavailable",
        )

    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"RailRadar returned HTTP {response.status_code}",
        )

    try:
        result = response.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="RailRadar returned invalid JSON",
        )

    return result


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