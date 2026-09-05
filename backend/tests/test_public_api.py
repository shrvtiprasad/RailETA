from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.middleware import rate_limiter


def sample_eta() -> dict:
    station = {
        "station_code": "JP",
        "station_name": "Jaipur Jn",
        "sequence": 2,
        "scheduled_arrival": "2026-09-06T10:00:00",
        "scheduled_departure": "2026-09-06T10:05:00",
        "predicted_arrival": "2026-09-06T10:05:00",
        "predicted_delay_minutes": 5.0,
        "prediction_source": "model",
        "confidence": "HIGH",
    }
    return {
        "train_number": "12250",
        "current_delay_minutes": 5.0,
        "prediction_source": "model",
        "confidence": "HIGH",
        "generated_at": "2026-09-06T10:00:00+05:30",
        "current_position": {"station_code": "MKN", "state": "running"},
        "stations": [station],
        "next_station": station,
        "stable_eta": {
            "current_eta": station["predicted_arrival"],
            "previous_eta": None,
            "change_minutes": None,
            "stability": "INSUFFICIENT_HISTORY",
            "reliability": "HIGH",
            "eta_range": None,
        },
    }


class PublicAPITests(unittest.TestCase):
    def setUp(self) -> None:
        rate_limiter.clear()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        rate_limiter.clear()

    def test_local_mode_does_not_require_a_key(self) -> None:
        with patch.dict(os.environ, {"RAILETA_REQUIRE_API_KEY": "false", "RAILETA_RATE_LIMIT_PER_MINUTE": "60"}, clear=False):
            response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response.headers)

    def test_missing_and_invalid_api_key_are_rejected_when_enabled(self) -> None:
        environment = {
            "RAILETA_REQUIRE_API_KEY": "true",
            "RAILETA_PUBLIC_API_KEY": "test-public-key",
            "RAILETA_RATE_LIMIT_PER_MINUTE": "60",
        }
        with patch.dict(os.environ, environment, clear=False):
            missing = self.client.get("/api/v1/health")
            invalid = self.client.get("/api/v1/health", headers={"X-API-Key": "wrong"})
            valid = self.client.get("/api/v1/health", headers={"X-API-Key": "test-public-key"})
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["error"]["code"], "INVALID_API_KEY")
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(valid.status_code, 200)

    def test_public_forecast_uses_shared_eta_result(self) -> None:
        with patch("backend.api.routes.public.generate_live_eta", return_value=sample_eta()):
            response = self.client.get("/api/v1/trains/12250/forecast")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stations"][0]["predicted_delay_minutes"], 5.0)
        self.assertEqual(response.json()["stations"][0]["status"], "PREDICTED")

    def test_live_endpoint_adds_summary_without_removing_frontend_payload(self) -> None:
        payload = {
            "data": {
                "trainNumber": "12250",
                "status": "running",
                "delayMinutes": 12,
                "currentLocation": {"stationCode": "JP", "stationName": "Jaipur Jn"},
                "route": [],
            }
        }
        with patch("backend.api.routes.trains.fetch_live_train", return_value=payload):
            response = self.client.get("/api/v1/trains/12250/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["train_number"], "12250")
        self.assertEqual(response.json()["current_station"]["code"], "JP")
        self.assertIn("data", response.json())

    def test_eta_endpoint_uses_the_shared_eta_service(self) -> None:
        with patch("backend.api.routes.eta.generate_live_eta", return_value=sample_eta()):
            response = self.client.get("/api/v1/trains/12250/eta")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prediction_source"], "model")
        self.assertTrue(response.json()["generated_at"])

    def test_public_explanation_and_connections_use_shared_eta_service(self) -> None:
        with patch("backend.api.routes.public.generate_live_eta", return_value=sample_eta()), patch(
            "backend.api.routes.public.calculate_connection_risk",
            return_value={"status": "unavailable", "reason": "No real service found", "reason_code": "NO_OUTGOING_TRAINS"},
        ):
            explanation = self.client.get("/api/v1/trains/12250/explanation")
            connections = self.client.get("/api/v1/trains/12250/connections")
        self.assertEqual(explanation.status_code, 200)
        self.assertEqual(explanation.json()["train_number"], "12250")
        self.assertEqual(connections.status_code, 200)
        self.assertEqual(connections.json()["reason_code"], "NO_OUTGOING_TRAINS")

    def test_public_route_returns_clean_fields(self) -> None:
        context = {
            "train": {
                "train_number": "12301",
                "train_name": "TEST SERVICE",
                "source_station_code": "HWH",
                "destination_station_code": "NDLS",
                "runs_days": "Daily",
            },
            "route": [
                {
                    "stationCode": "HWH",
                    "stationName": "Howrah Jn",
                    "sequence": 1,
                    "dayOffset": 0,
                    "scheduledArrival": "—",
                    "scheduledDeparture": "10:00",
                }
            ],
        }
        with patch("backend.api.routes.public.load_static_train_context", return_value=context):
            response = self.client.get("/api/v1/trains/12301/route")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stops"][0]["station_code"], "HWH")
        self.assertNotIn("connection", response.json())

    def test_rate_limit_returns_429(self) -> None:
        with patch.dict(os.environ, {"RAILETA_REQUIRE_API_KEY": "false", "RAILETA_RATE_LIMIT_PER_MINUTE": "1"}, clear=False):
            first = self.client.get("/api/v1/health")
            second = self.client.get("/api/v1/health")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["error"]["code"], "RATE_LIMIT_EXCEEDED")

    def test_invalid_train_number_is_structured(self) -> None:
        with patch.dict(os.environ, {"RAILETA_REQUIRE_API_KEY": "false", "RAILETA_RATE_LIMIT_PER_MINUTE": "60"}, clear=False):
            response = self.client.get("/api/v1/trains/not-a-train/forecast")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
