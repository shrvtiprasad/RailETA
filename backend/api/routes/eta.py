from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.services.eta import generate_live_eta
from backend.api.services.railradar import RailRadarError
from backend.ml.contract import DataUnavailableError


router = APIRouter(prefix="/trains", tags=["ETA Prediction"])


@router.get("/{train_number}/eta")
async def predict_train_eta(train_number: str):
    try:
        return await generate_live_eta(train_number)
    except RailRadarError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except DataUnavailableError as exc:
        message = str(exc)
        status_code = 422 if "no upcoming station" in message.lower() else 502
        raise HTTPException(status_code=status_code, detail=message) from exc
