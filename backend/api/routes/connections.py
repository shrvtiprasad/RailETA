from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.api.services.connections import calculate_connection_risk, connection_debug
from backend.api.services.eta import generate_live_eta
from backend.api.services.railradar import RailRadarError
from backend.ml.contract import DataUnavailableError


router = APIRouter(prefix="/connections", tags=["Connection Risk"])


@router.get("/risk")
async def get_connection_risk(
    current_train_number: str = Query(..., min_length=1),
    connecting_train_number: str | None = Query(default=None, min_length=1),
    connection_station: str | None = Query(default=None, min_length=2),
):
    try:
        current_result = await generate_live_eta(current_train_number)
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        status = 422 if "no upcoming station" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return calculate_connection_risk(current_result, connecting_train_number, connection_station)


@router.get("/debug")
async def debug_connection_risk(
    current_train_number: str = Query(..., min_length=1),
):
    """Development diagnostics for automatic timetable candidate discovery."""

    try:
        current_result = await generate_live_eta(current_train_number)
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        status = 422 if "no upcoming station" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return connection_debug(current_result)
