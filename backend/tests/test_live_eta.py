from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.services.eta import predict_live_eta
from backend.ml.contract import DataUnavailableError


def live_payload() -> dict:
    return {
        "data": {
            "trainNo": "12301",
            "status": "running",
            "delayMinutes": 12,
            "currentLocation": {"stationCode": "NDLS", "sequence": 1, "lat": 28.64, "lng": 77.22},
            "route": [
                {
                    "stationCode": "NDLS",
                    "stationName": "NEW DELHI",
                    "sequence": 1,
                    "scheduledDeparture": "17:00",
                    "status": "current",
                },
                {
                    "stationCode": "CNB",
                    "stationName": "KANPUR CENTRAL",
                    "sequence": 2,
                    "scheduledArrival": "22:00",
                    "dayOffset": 0,
                    "status": "upcoming",
                },
            ],
        }
    }


class FakePipeline:
    def predict(self, frame):
        return [7.5] * len(frame)


class SequentialFakePipeline:
    def predict(self, frame):
        return [float(frame["current_departure_delay_minutes"].iloc[0]) + 1]


def railway_artifact() -> dict:
    return {
        "model_version": "test-model",
        "categorical_features": ["train_number", "current_station_code", "next_station_code"],
        "numeric_features": ["current_departure_delay_minutes", "scheduled_section_runtime_minutes"],
        "weather_included": False,
        "pipeline": FakePipeline(),
    }


class LiveEtaInferenceTests(unittest.TestCase):
    def test_successful_model_inference(self) -> None:
        payload = live_payload()
        payload["data"]["trainType"] = {"code": "RAJ", "name": "Rajdhani"}
        payload["data"]["sourceStationCode"] = {"code": "HWH"}
        payload["data"]["destinationStationCode"] = {"code": "NDLS"}
        with patch("backend.api.services.eta.load_artifact", return_value=railway_artifact()):
            result = predict_live_eta(payload, {"temperature_2m": 31, "weather_code": 1})

        self.assertEqual(result["prediction_source"], "model")
        self.assertEqual(result["next_station"]["station_code"], "CNB")
        self.assertEqual(result["next_station"]["predicted_delay_minutes"], 7.5)
        self.assertEqual(result["current_position"]["state"], "running")

    def test_missing_weather_falls_back_when_weather_is_required_by_artifact(self) -> None:
        artifact = railway_artifact()
        artifact["weather_included"] = True
        artifact["numeric_features"] = ["current_departure_delay_minutes", "temperature_2m"]
        with patch("backend.api.services.eta.load_artifact", return_value=artifact):
            result = predict_live_eta(live_payload(), None)

        self.assertEqual(result["prediction_source"], "baseline")
        self.assertEqual(result["next_station"]["predicted_delay_minutes"], 12.0)
        self.assertIn("temperature_2m", result["missing_live_features"])

    def test_downstream_sections_use_previous_section_prediction(self) -> None:
        artifact = railway_artifact()
        artifact["pipeline"] = SequentialFakePipeline()
        payload = live_payload()
        payload["data"]["route"].append(
            {
                "stationCode": "HWH",
                "stationName": "HOWRAH CENTRAL",
                "sequence": 3,
                "scheduledArrival": "2026-04-16T02:00:00",
                "status": "upcoming",
            }
        )
        with patch("backend.api.services.eta.load_artifact", return_value=artifact):
            result = predict_live_eta(payload, None)

        self.assertEqual(result["stations"][0]["predicted_delay_minutes"], 13.0)
        self.assertEqual(result["stations"][1]["predicted_delay_minutes"], 14.0)

    def test_missing_model_falls_back_to_current_delay(self) -> None:
        with patch(
            "backend.api.services.eta.load_artifact",
            side_effect=DataUnavailableError("trained ETA model was not found"),
        ):
            result = predict_live_eta(live_payload(), None, model_path=Path("/missing/model.joblib"))

        self.assertEqual(result["prediction_source"], "baseline")
        self.assertEqual(result["next_station"]["predicted_delay_minutes"], 12.0)
        self.assertEqual(result["confidence"], "LOW")

    def test_malformed_live_api_response_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "malformed data"):
            predict_live_eta({"data": []}, None)

    def test_no_upcoming_station_is_rejected(self) -> None:
        payload = live_payload()
        payload["data"]["route"] = [payload["data"]["route"][0]]
        with self.assertRaisesRegex(DataUnavailableError, "no upcoming station"):
            predict_live_eta(payload, None)


if __name__ == "__main__":
    unittest.main()
