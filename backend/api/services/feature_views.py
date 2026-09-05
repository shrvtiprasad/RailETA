from __future__ import annotations

from typing import Any


def eta_station(result: dict[str, Any]) -> dict[str, Any] | None:
    station = result.get("next_station")
    if isinstance(station, dict):
        return station
    stations = result.get("stations")
    if isinstance(stations, list) and stations and isinstance(stations[0], dict):
        return stations[0]
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    except (TypeError, ValueError):
        return None


def delay_summary(result: dict[str, Any]) -> dict[str, Any]:
    station = eta_station(result) or {}
    current = _number(result.get("current_delay_minutes"))
    final = _number(station.get("predicted_delay_minutes"))
    additional = round(final - current, 2) if current is not None and final is not None else None
    recovery = round(current - final, 2) if current is not None and final is not None and final < current else None
    station_name = station.get("station_name") or station.get("station_code") or "the next station"
    factors: list[str] = []
    if current is not None and current > 0:
        factors.append("current carried RailRadar delay")
    if current is not None and final is not None and final > current:
        factors.append("remaining section characteristics")
    elif current is not None and final is not None and final < current:
        factors.append("predicted recovery across remaining sections")
    if station.get("weather_context") is not None:
        factors.append("weather conditions considered by the model")
    if not factors:
        factors.append("available scheduled and live route features")

    if current is None or final is None:
        explanation = "A complete delay explanation is unavailable because the live delay or model result is missing."
    elif additional is not None and additional > 0:
        explanation = (
            f"Train is currently {round(current)} min late. The model predicts a final delay of "
            f"approximately {round(final)} min at {station_name}, or about {round(additional)} additional minutes."
        )
    elif recovery is not None and recovery > 0:
        explanation = (
            f"Train is currently {round(current)} min late. The model predicts approximately "
            f"{round(recovery)} min recovery by {station_name}, leaving a final delay of about {round(final)} min."
        )
    else:
        explanation = f"Train is currently about {round(current)} min late, with a predicted final delay of about {round(final)} min at {station_name}."

    weather_available = station.get("weather_context") is not None
    if weather_available:
        explanation += " Live weather was retrieved as prediction context; it is not evidence of delay causation."

    return {
        "train_number": result.get("train_number"),
        "current_delay_minutes": current,
        "predicted_final_delay_minutes": final,
        "predicted_additional_delay_minutes": additional,
        "expected_recovery_minutes": recovery,
        "current_status": (result.get("current_position") or {}).get("state"),
        "upcoming_station": station,
        "explanation": explanation,
        "likely_contributing_factors": factors,
        "explanation_factors": factors,
        "weather_context_available": weather_available,
        "weather_influence": "considered_by_model_not_causal" if weather_available else "unavailable",
        "prediction_source": result.get("prediction_source"),
        "confidence": result.get("confidence"),
        "data_quality": result.get("data_quality"),
    }


def delay_propagation(result: dict[str, Any]) -> dict[str, Any]:
    station = eta_station(result) or {}
    current = _number(result.get("current_delay_minutes"))
    downstream: list[dict[str, Any]] = []
    for item in result.get("stations", []):
        if not isinstance(item, dict):
            continue
        predicted = _number(item.get("predicted_delay_minutes"))
        additional = round(predicted - current, 2) if current is not None and predicted is not None else None
        downstream.append(
            {
                "station_code": item.get("station_code"),
                "station_name": item.get("station_name"),
                "scheduled_arrival": item.get("scheduled_arrival"),
                "predicted_arrival": item.get("predicted_arrival"),
                "section_current_delay_minutes": _number(item.get("section_current_delay_minutes")),
                "predicted_delay_minutes": predicted,
                "predicted_additional_delay_minutes": additional,
                "delay_change_minutes": additional,
                "prediction_source": item.get("prediction_source"),
                "confidence": item.get("confidence"),
            }
        )
    predicted_values = [item["predicted_delay_minutes"] for item in downstream if item["predicted_delay_minutes"] is not None]
    max_delay = max(predicted_values) if predicted_values else None
    return {
        "train_number": result.get("train_number"),
        "current_delay_minutes": current,
        "upcoming_station": station,
        "downstream_impact": {
            "maximum_predicted_delay_minutes": max_delay,
            "affected_downstream_station_count": len(predicted_values),
            "description": (
                "Current train route propagation across the remaining predicted sections."
                if predicted_values
                else "Current train route propagation is unavailable because no station predictions were returned."
            ),
        },
        "affected_downstream_stations": downstream,
        "prediction_source": result.get("prediction_source"),
        "confidence": result.get("confidence"),
        "data_quality": result.get("data_quality"),
    }


def stable_eta_view(result: dict[str, Any]) -> dict[str, Any]:
    stable = result.get("stable_eta")
    if isinstance(stable, dict):
        return {"train_number": result.get("train_number"), **stable}
    station = eta_station(result) or {}
    return {
        "train_number": result.get("train_number"),
        "current_eta": station.get("predicted_arrival"),
        "eta_range": None,
        "previous_eta": None,
        "change_minutes": None,
        "stability": "UNAVAILABLE",
        "reliability": station.get("confidence") or result.get("confidence"),
        "prediction_timestamp": None,
        "history_count_for_station": 0,
        "generated_at": result.get("generated_at"),
    }
