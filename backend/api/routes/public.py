from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Security
from fastapi.security import APIKeyHeader

from backend.api.schemas import ConnectionResponse, ExplanationResponse, ForecastResponse, RouteResponse
from backend.api.services.connections import calculate_connection_risk
from backend.api.services.eta import generate_live_eta, load_static_train_context, merge_static_context
from backend.api.services.feature_views import delay_summary
from backend.api.services.railradar import RailRadarError, fetch_live_train
from backend.ml.contract import DataUnavailableError


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
router = APIRouter(
    prefix="/trains",
    tags=["Public v1"],
    dependencies=[Security(api_key_header)],
)
TRAIN_PATH = Path(..., pattern=r"^\d{5}$", description="Five-digit Indian Railways train number")


def _raise_upstream(exc: Exception) -> None:
    if isinstance(exc, RailRadarError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if isinstance(exc, DataUnavailableError):
        status = 422 if "no upcoming station" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


async def _eta(train_number: str) -> dict[str, Any]:
    try:
        return await generate_live_eta(train_number)
    except (RailRadarError, DataUnavailableError) as exc:
        _raise_upstream(exc)
        raise AssertionError("unreachable")


@router.get(
    "/{train_number}/forecast",
    response_model=ForecastResponse,
    summary="Get the recursive downstream ETA forecast",
    description="Uses the existing saved XGBoost artifact and shared section-by-section ETA state for every remaining station.",
)
async def get_forecast(train_number: str = TRAIN_PATH) -> dict[str, Any]:
    result = await _eta(train_number)
    stations = []
    for index, item in enumerate(result.get("stations", [])):
        if not isinstance(item, dict):
            continue
        stations.append(
            {
                "station_code": item.get("station_code"),
                "station_name": item.get("station_name"),
                "sequence": item.get("sequence", index + 1),
                "scheduled_arrival": item.get("scheduled_arrival"),
                "scheduled_departure": item.get("scheduled_departure"),
                "predicted_arrival": item.get("predicted_arrival"),
                "predicted_departure": item.get("predicted_departure"),
                "predicted_delay_minutes": item.get("predicted_delay_minutes"),
                "prediction_source": item.get("prediction_source"),
                "confidence": item.get("confidence"),
                "status": "PREDICTED" if item.get("predicted_arrival") else "UNAVAILABLE",
            }
        )
    return {
        "train_number": result.get("train_number", train_number),
        "current_delay_minutes": result.get("current_delay_minutes"),
        "prediction_source": result.get("prediction_source"),
        "confidence": result.get("confidence"),
        "generated_at": result.get("generated_at"),
        "stations": stations,
    }


@router.get(
    "/{train_number}/explanation",
    response_model=ExplanationResponse,
    summary="Explain the current delay and predicted recovery",
    description="Returns passenger-friendly factors without claiming that a factor caused the delay.",
)
async def get_explanation(train_number: str = TRAIN_PATH) -> dict[str, Any]:
    result = await _eta(train_number)
    return delay_summary(result)


@router.get(
    "/{train_number}/connections",
    response_model=ConnectionResponse,
    summary="Find real scheduled onward connections",
    description="Compares the incoming train's shared ML ETA with scheduled departures from the local SQLite timetable; outgoing trains do not require live status.",
)
async def get_connections(
    train_number: str = TRAIN_PATH,
    connection_station: str | None = Query(default=None, min_length=2, description="Optional station code; automatic mode searches the remaining route when omitted."),
) -> dict[str, Any]:
    result = await _eta(train_number)
    return calculate_connection_risk(result, None, connection_station)


@router.get(
    "/{train_number}/route",
    response_model=RouteResponse,
    summary="Get a clean train route and timetable",
    description="Returns useful route fields from the local timetable or the current RailRadar route without exposing database internals.",
)
async def get_route(train_number: str = TRAIN_PATH) -> dict[str, Any]:
    context = load_static_train_context(train_number)
    if context is None:
        try:
            payload = await fetch_live_train(train_number)
        except RailRadarError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        context = {"train": {}, "route": []}
        merged = merge_static_context(payload, None)
        data = merged.get("data", merged)
        context["train"] = data.get("train") if isinstance(data.get("train"), dict) else {}
        route = data.get("route") if isinstance(data.get("route"), list) else []
        context["route"] = route

    train = context.get("train") if isinstance(context.get("train"), dict) else {}
    route = context.get("route") if isinstance(context.get("route"), list) else []
    if not route:
        raise HTTPException(status_code=404, detail={"code": "ROUTE_NOT_FOUND", "message": "No route data is available for this train."})
    stops = []
    for item in route:
        if not isinstance(item, dict):
            continue
        stops.append(
            {
                "station_code": item.get("stationCode") or item.get("station_code") or item.get("code"),
                "station_name": item.get("stationName") or item.get("station_name") or item.get("name"),
                "sequence": item.get("sequence") or item.get("seq"),
                "day_offset": item.get("dayOffset") if item.get("dayOffset") is not None else item.get("day_offset"),
                "scheduled_arrival": item.get("scheduledArrival") or item.get("arrival_time"),
                "scheduled_departure": item.get("scheduledDeparture") or item.get("departure_time"),
                "halt_minutes": item.get("haltMinutes") if item.get("haltMinutes") is not None else item.get("halt_minutes"),
                "latitude": item.get("lat") if item.get("lat") is not None else item.get("latitude"),
                "longitude": item.get("lng") if item.get("lng") is not None else item.get("longitude"),
            }
        )
    return {
        "train_number": str(train.get("train_number") or train.get("number") or train_number),
        "train_name": train.get("train_name") or train.get("name"),
        "source_station_code": train.get("source_station_code") or train.get("sourceCode"),
        "destination_station_code": train.get("destination_station_code") or train.get("destinationCode"),
        "runs_days": train.get("runs_days") or ", ".join(train.get("runDays", [])) if isinstance(train.get("runDays"), list) else train.get("runDays"),
        "stops": stops,
    }
