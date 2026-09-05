from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from backend.ml.live_features import build_live_rows
from backend.ml.contract import DataUnavailableError
from backend.ml.railkit import RailKitHistoryClient, normalize_history
from backend.ml.ingestion.batch import collect_batch


class RailKitNormalizationTests(unittest.TestCase):
    def test_missing_manifest_is_non_blocking_and_makes_no_history_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = Mock()
            client.quota_status.side_effect = [
                {"limit": 50, "used": 10, "remaining": 40, "locally_recorded_usage": 10},
                {"limit": 50, "used": 10, "remaining": 40, "locally_recorded_usage": 10},
            ]
            with patch("backend.ml.ingestion.batch.RailKitHistoryClient", return_value=client):
                report = collect_batch(
                    journeys_path=root / "missing-journeys.csv",
                    events_path=root / "events.csv",
                    report_path=root / "report.json",
                    unavailable_path=root / "unavailable.csv",
                )

        client.fetch_history.assert_not_called()
        self.assertEqual(report["requested_pairs"], 0)
        self.assertFalse(report["historical_collection"]["manifest_present"])
        self.assertEqual(report["historical_collection"]["railkit_calls_made"], 0)

    def test_quota_uses_provider_snapshot_without_losing_local_usage(self) -> None:
        month = datetime.now().strftime("%Y-%m")
        with tempfile.TemporaryDirectory() as directory:
            usage_path = Path(directory) / "railkit_usage.json"
            usage_path.write_text(json.dumps({"months": {month: 5}}), encoding="utf-8")
            previous = os.environ.get("RAILKIT_PROVIDER_REMAINING_REQUESTS")
            os.environ["RAILKIT_PROVIDER_REMAINING_REQUESTS"] = "40"
            try:
                status = RailKitHistoryClient(
                    usage_path=usage_path,
                    monthly_limit=50,
                ).quota_status()
            finally:
                if previous is None:
                    os.environ.pop("RAILKIT_PROVIDER_REMAINING_REQUESTS", None)
                else:
                    os.environ["RAILKIT_PROVIDER_REMAINING_REQUESTS"] = previous

        self.assertEqual(status["limit"], 50)
        self.assertEqual(status["locally_recorded_usage"], 5)
        self.assertEqual(status["provider_reported_remaining"], 40)
        self.assertEqual(status["provider_implied_usage"], 10)
        self.assertEqual(status["used"], 10)
        self.assertEqual(status["remaining"], 40)

    def test_provider_error_is_not_reported_as_empty_history(self) -> None:
        with self.assertRaisesRegex(DataUnavailableError, "Invalid API key"):
            normalize_history({"success": False, "error": "Invalid API key"}, "12301", "15-04-2025")

    def test_history_normalizes_real_provider_shape_and_midnight(self) -> None:
        payload = {
            "success": True,
            "data": {
                "trainNo": "12301",
                "journeyDate": "15-04-2025",
                "stations": [
                    {
                        "stationCode": "NDLS",
                        "stationName": "NEW DELHI",
                        "distanceKm": 0,
                        "arrival": {"scheduled": "SRC", "actual": "SRC", "delay": 0},
                        "departure": {"scheduled": "17:00", "actual": "17:05", "delay": 5},
                    },
                    {
                        "stationCode": "HWH",
                        "stationName": "HOWRAH JN",
                        "distanceKm": 1447,
                        "arrival": {"scheduled": "09:55", "actual": "10:10", "delay": 15},
                        "departure": {"scheduled": "10:00", "actual": "10:15", "delay": 15},
                    },
                ],
            },
        }
        rows = normalize_history(payload, "12301", "15-04-2025")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["station_code"], "NDLS")
        self.assertEqual(rows[1]["distance_from_origin"], 1447)
        self.assertTrue(rows[1]["scheduled_arrival"].startswith("2025-04-16T09:55"))
        self.assertTrue(rows[1]["actual_arrival"].startswith("2025-04-16T10:10"))


class LiveFeatureTests(unittest.TestCase):
    def test_live_route_produces_upcoming_section_rows_without_target_labels(self) -> None:
        payload = {
            "data": {
                "trainNo": "12301",
                "delayMinutes": 12,
                "currentLocation": {"stationCode": "NDLS", "sequence": 1},
                "route": [
                    {"stationCode": "NDLS", "stationName": "NEW DELHI", "sequence": 1, "isHalt": True, "scheduledDeparture": "17:00"},
                    {"stationCode": "CNB", "stationName": "KANPUR", "sequence": 2, "isHalt": True, "scheduledArrival": "22:00", "lat": 26.4499, "lng": 80.3319},
                ],
            }
        }
        rows = build_live_rows(payload, {"temperature_2m": 30, "weather_code": 1})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["next_station_code"], "CNB")
        self.assertEqual(rows[0]["current_departure_delay_minutes"], 12)
        self.assertEqual(rows[0]["is_raining"], 0.0)
        self.assertNotIn("next_station_arrival_delay_minutes", rows[0])


if __name__ == "__main__":
    unittest.main()
