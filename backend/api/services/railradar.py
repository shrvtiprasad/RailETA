from __future__ import annotations

import os
import logging
import ssl
from pathlib import Path
from typing import Any

import certifi
import httpx
from dotenv import load_dotenv

try:
    import truststore
except ImportError:  # pragma: no cover - exercised only before dependency installation
    truststore = None


BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env", override=False)
BASE_URL = os.getenv("RAILRADAR_BASE_URL", "https://api.railradar.in/v1")
logger = logging.getLogger(__name__)


def _ca_bundle() -> str | ssl.SSLContext:
    """Use an explicit CA bundle, then the OS trust store, then certifi.

    The OS trust store is important on macOS and Windows when a managed
    network installs a trusted proxy/root certificate locally.
    """

    configured = os.getenv("RAILRADAR_CA_BUNDLE", "").strip() or os.getenv("SSL_CERT_FILE", "").strip()
    if configured:
        bundle = Path(configured).expanduser()
        if not bundle.is_file():
            raise RailRadarError(f"Configured RailRadar CA bundle was not found at {bundle}", 500)
        return str(bundle)
    if truststore is not None:
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return certifi.where()


class RailRadarError(Exception):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


async def fetch_live_train(train_number: str) -> dict[str, Any]:
    api_key = os.getenv("RAILRADAR_API_KEY", "").strip()
    if not api_key:
        logger.warning("RailRadar API key is not configured")
        raise RailRadarError("RAILRADAR_API_KEY is not configured", 503)
    url = f"{BASE_URL}/trains/{train_number}/live"
    params = {
        "authoritative": "true",
        "geometry": "true",
        "format": "geojson",
        "includeCoordinates": "true",
    }
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=_ca_bundle()) as client:
            response = await client.get(url, headers=headers, params=params)
    except RailRadarError:
        raise
    except httpx.TimeoutException as exc:
        logger.warning("RailRadar request timed out train=%s", train_number)
        raise RailRadarError("RailRadar request timed out", 504) from exc
    except httpx.ConnectError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            logger.warning("RailRadar TLS certificate verification failed train=%s", train_number)
            raise RailRadarError(
                "RailRadar TLS certificate verification failed. Update certifi or set "
                "RAILRADAR_CA_BUNDLE to a trusted PEM CA bundle in backend/.env.",
                502,
            ) from exc
        logger.warning("RailRadar connection failed train=%s error=%s", train_number, exc)
        raise RailRadarError(f"Could not connect to RailRadar: {exc}", 503) from exc
    except httpx.RequestError as exc:
        logger.warning("RailRadar request failed train=%s error=%s", train_number, exc)
        raise RailRadarError(f"Could not connect to RailRadar: {exc}", 503) from exc

    if response.status_code == 401:
        logger.warning("RailRadar authentication failed train=%s", train_number)
        raise RailRadarError("RailRadar API authentication failed", 502)
    if response.status_code == 404:
        logger.warning("RailRadar live data not found train=%s", train_number)
        raise RailRadarError(f"Live data for train {train_number} was not found on RailRadar", 404)
    if response.status_code == 429:
        logger.warning("RailRadar request limit reached train=%s", train_number)
        raise RailRadarError("RailRadar API request limit reached", 429)
    if response.status_code >= 500:
        logger.warning("RailRadar upstream failure train=%s status=%s", train_number, response.status_code)
        raise RailRadarError("RailRadar live service is temporarily unavailable", 502)
    if not response.is_success:
        logger.warning("RailRadar returned HTTP error train=%s status=%s", train_number, response.status_code)
        raise RailRadarError(f"RailRadar returned HTTP {response.status_code}", 502)
    try:
        result = response.json()
    except ValueError as exc:
        logger.warning("RailRadar returned invalid JSON train=%s", train_number)
        raise RailRadarError("RailRadar returned invalid JSON", 502) from exc
    if not isinstance(result, dict):
        logger.warning("RailRadar returned unexpected response shape train=%s", train_number)
        raise RailRadarError("RailRadar returned an unexpected response shape", 502)
    return result
