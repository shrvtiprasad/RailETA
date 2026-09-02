import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException

import certifi
# backend/.env
BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

RAILRADAR_API_KEY = os.getenv("RAILRADAR_API_KEY")

router = APIRouter(prefix="/trains", tags=["Live Trains"])

RAILRADAR_BASE_URL = "https://api.railradar.in/v1"


@router.get("/{train_number}/live")
async def get_live_train(train_number: str):

    if not RAILRADAR_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="RAILRADAR_API_KEY is not configured",
        )

    url = f"{RAILRADAR_BASE_URL}/trains/{train_number}/live"

    headers = {
        "Authorization": f"Bearer {RAILRADAR_API_KEY}"
    }

    try:
        async with httpx.AsyncClient(
        timeout=15.0,
        verify=certifi.where(),
        ) as client:
           params = {
                "authoritative": "true",
                "geometry": "true",
                "format": "geojson",
                "includeCoordinates": "true",
            }
           response = await client.get(
                url,
                headers=headers,
                params=params,
            )

        if response.status_code == 401:
            raise HTTPException(
                status_code=502,
                detail="RailRadar API key is invalid or expired",
            )

        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Live data not found for train {train_number}",
            )

        if response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="RailRadar API quota exceeded",
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"RailRadar API returned status {response.status_code}",
            )

        return response.json()

    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to RailRadar: {exc}",
        )