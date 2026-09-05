from __future__ import annotations

import unittest
from datetime import date, timedelta

from backend.api.services.connections import _connection_from_values, connection_debug
from backend.api.services.eta import load_static_train_context


class ConnectionRiskTests(unittest.TestCase):
    def test_real_local_timetable_is_scanned_across_remaining_route(self) -> None:
        context = load_static_train_context("12301")
        self.assertIsNotNone(context)
        assert context is not None
        self.assertGreater(len(context["route"]), 3)
        base = date.today() + timedelta(days=1)
        stations = []
        for stop in context["route"][1:]:
            arrival = stop.get("scheduledArrival") or "12:00"
            stations.append(
                {
                    "station_code": stop["stationCode"],
                    "station_name": stop["stationName"],
                    "predicted_arrival": f"{base.isoformat()}T{arrival}:00",
                    "prediction_source": "model",
                    "confidence": "HIGH",
                }
            )
        result = {
            "train_number": "12301",
            "current_position": {"station_code": "HWH"},
            "stations": stations,
            "next_station": stations[0],
        }
        diagnostics = connection_debug(result)
        self.assertEqual(diagnostics["stations_checked"], len(stations))
        self.assertGreater(diagnostics["candidate_outgoing_trains_found"], 0)
        self.assertGreaterEqual(diagnostics["rejection_reasons"]["same_train"], 1)
        self.assertEqual(len(diagnostics["station_diagnostics"]), len(stations))
        self.assertIn("outgoing_trains", diagnostics["station_diagnostics"][0])

    def test_risk_formula_handles_positive_negative_and_missed_margins(self) -> None:
        result = {"train_number": "TEST", "stations": []}
        station = {
            "station_code": "NDLS",
            "station_name": "NEW DELHI",
            "predicted_arrival": "2026-09-06T23:50:00",
            "prediction_source": "model",
            "confidence": "HIGH",
        }
        low = _connection_from_values(result, "12001", "TEST SERVICE", "NDLS", station, "2026-09-07T00:30:00", 0)
        high = _connection_from_values(result, "12001", "TEST SERVICE", "NDLS", station, "2026-09-06T23:55:00", 0)
        missed = _connection_from_values(result, "12001", "TEST SERVICE", "NDLS", station, "2026-09-06T23:40:00", 0)
        self.assertEqual(low["risk"], "LOW")
        self.assertEqual(low["connection_margin_minutes"], 30.0)
        self.assertEqual(high["risk"], "HIGH")
        self.assertEqual(missed["risk"], "MISSED")

    def test_missing_prediction_is_reported(self) -> None:
        diagnostics = connection_debug(
            {
                "train_number": "TEST",
                "stations": [{"station_code": "NDLS", "predicted_arrival": None}],
            }
        )
        self.assertEqual(diagnostics["rejection_reasons"]["missing_prediction"], 1)

    def test_no_remaining_route_is_reported(self) -> None:
        diagnostics = connection_debug({"train_number": "TEST", "stations": []})
        self.assertEqual(diagnostics["reason_code"], "no_remaining_route")


if __name__ == "__main__":
    unittest.main()
