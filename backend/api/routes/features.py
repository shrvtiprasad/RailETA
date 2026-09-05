from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.services.eta import generate_live_eta
from backend.api.services.feature_views import delay_propagation, delay_summary, stable_eta_view
from backend.api.services.railradar import RailRadarError
from backend.ml.contract import DataUnavailableError


router = APIRouter(prefix="/trains", tags=["Prediction Features"])


async def _eta_or_http_error(train_number: str) -> dict:
    try:
        return await generate_live_eta(train_number)
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        status = 422 if "no upcoming station" in str(exc).lower() else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/{train_number}/delay-explanation")
async def get_delay_explanation(train_number: str):
    result = await _eta_or_http_error(train_number)
    return delay_summary(result)


@router.get("/{train_number}/delay-recovery")
async def get_delay_recovery(train_number: str):
    result = await _eta_or_http_error(train_number)
    summary = delay_summary(result)
    return {"status": "available", **summary}


@router.get("/{train_number}/delay-propagation")
async def get_delay_propagation(train_number: str):
    result = await _eta_or_http_error(train_number)
    return delay_propagation(result)


@router.get("/{train_number}/stable-eta")
async def get_stable_eta(train_number: str):
    result = await _eta_or_http_error(train_number)
    return stable_eta_view(result)
