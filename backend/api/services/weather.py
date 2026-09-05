from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import ssl
import time
from typing import Any

import certifi
import httpx
from dotenv import load_dotenv

try:
    import truststore
except ImportError:  # pragma: no cover - exercised only before dependency installation
    truststore = None


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
BASE_URL = os.getenv("OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast")
WEATHER_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "weather_code",
]
_cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


def _verify_context() -> str | ssl.SSLContext:
    """Use the configured CA bundle, then the OS store, then certifi.

    truststore lets Python/httpx use macOS Keychain or the Windows system
    certificate store while retaining normal certificate verification.
    """

    configured = os.getenv("OPEN_METEO_CA_BUNDLE", "").strip() or os.getenv("SSL_CERT_FILE", "").strip()
    if configured:
        bundle = Path(configured).expanduser()
        if not bundle.is_file():
            raise RuntimeError(f"Configured Open-Meteo CA bundle was not found at {bundle}")
        return str(bundle)
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return certifi.where()


async def current_weather(latitude: float, longitude: float, ttl_seconds: int = 600) -> dict[str, Any]:
    key = (round(float(latitude), 4), round(float(longitude), 4))
    now = time.monotonic()
    async with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < ttl_seconds:
            return cached[1]

    params = {
        "latitude": key[0],
        "longitude": key[1],
        "current": ",".join(WEATHER_VARIABLES),
        "timezone": "Asia/Kolkata",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=_verify_context()) as client:
            response = await client.get(BASE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
        logger.warning("Open-Meteo forecast request failed lat=%s lon=%s error=%s", key[0], key[1], exc)
        raise RuntimeError(f"Open-Meteo forecast request failed: {exc}") from exc
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        logger.warning("Open-Meteo forecast returned malformed current weather lat=%s lon=%s", key[0], key[1])
        raise RuntimeError("Open-Meteo forecast response did not contain current weather")
    result = {column: current.get(column) for column in WEATHER_VARIABLES}
    async with _cache_lock:
        _cache[key] = (time.monotonic(), result)
    return result
