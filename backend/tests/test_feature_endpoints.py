from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.main import app


def sample_eta() -> dict:
    return {
        "train_number": "12250",
        "current_position": {"station_code": "DO", "state": "running"},
        "current_delay_minutes": 26.0,
        "prediction_source": "model",
        "confidence": "HIGH",
        "data_quality": "HIGH",
        "next_station": {
            "station_code": "AWR",
            "station_name": "Alwar Jn",
            "scheduled_arrival": "2026-09-03T05:29:00",
            "predicted_arrival": "2026-09-03T05:41:00",
            "predicted_delay_minutes": 12.0,
            "prediction_source": "model",
            "confidence": "HIGH",
            "weather_context": {"temperature_2m": 26.4},
            "important_contributing_factors": ["current RailRadar delay"],
        },
        "stations": [],
        "stable_eta": {
            "current_eta": "2026-09-03T05:41:00",
            "previous_eta": "2026-09-03T05:39:00",
            "change_minutes": 2.0,
            "stability": "STABLE",
            "reliability": "HIGH",
            "prediction_timestamp": "2026-09-03T05:00:00+00:00",
            "history_count_for_station": 2,
            "eta_range": {
                "lower": "2026-09-03T05:34:18",
                "upper": "2026-09-03T05:47:42",
            },
        },
    }


class FeatureEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_feature_endpoints_reuse_live_eta_result(self) -> None:
        with patch("backend.api.routes.features.generate_live_eta", return_value=sample_eta()):
            explanation = self.client.get("/api/v1/trains/12250/delay-explanation")
            recovery = self.client.get("/api/v1/trains/12250/delay-recovery")
            propagation = self.client.get("/api/v1/trains/12250/delay-propagation")
            stable = self.client.get("/api/v1/trains/12250/stable-eta")

        self.assertEqual(explanation.status_code, 200)
        self.assertEqual(explanation.json()["predicted_final_delay_minutes"], 12.0)
        self.assertEqual(recovery.json()["status"], "available")
        self.assertEqual(propagation.json()["train_number"], "12250")
        self.assertEqual(stable.json()["stability"], "STABLE")

    def test_connection_endpoint_uses_real_connection_service(self) -> None:
        expected = {
            "status": "calculated",
            "connecting_train_number": "12951",
            "risk": "LOW",
            "connection_time_minutes": 42.0,
        }
        with patch("backend.api.routes.connections.generate_live_eta", return_value=sample_eta()), patch(
            "backend.api.routes.connections.calculate_connection_risk", return_value=expected
        ):
            response = self.client.get(
                "/api/v1/connections/risk",
                params={
                    "current_train_number": "12250",
                    "connecting_train_number": "12951",
                    "connection_station": "AWR",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)

    def test_connection_endpoint_allows_automatic_local_timetable_detection(self) -> None:
        expected = {
            "status": "unavailable",
            "reason": "No connecting journey detected from the available local timetable.",
            "automatic_detection": True,
            "candidates": [],
        }
        with patch("backend.api.routes.connections.generate_live_eta", return_value=sample_eta()), patch(
            "backend.api.routes.connections.calculate_connection_risk", return_value=expected
        ) as calculate:
            response = self.client.get(
                "/api/v1/connections/risk",
                params={
                    "current_train_number": "12250",
                    "connection_station": "AWR",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        calculate.assert_called_once_with(sample_eta(), None, "AWR")


if __name__ == "__main__":
    unittest.main()
