from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StationReference(BaseModel):
    code: str | None = None
    name: str | None = None


class LiveTrainResponse(BaseModel):
    train_number: str
    status: str | None = None
    current_station: StationReference | None = None
    current_delay_minutes: float | None = None
    updated_at: str | None = None


class ForecastStation(BaseModel):
    station_code: str | None = None
    station_name: str | None = None
    sequence: int | float | None = None
    scheduled_arrival: str | None = None
    scheduled_departure: str | None = None
    predicted_arrival: str | None = None
    predicted_departure: str | None = None
    predicted_delay_minutes: float | None = None
    prediction_source: str | None = None
    confidence: str | None = None
    status: str = "PREDICTED"


class ForecastResponse(BaseModel):
    train_number: str
    current_delay_minutes: float | None = None
    prediction_source: str | None = None
    confidence: str | None = None
    generated_at: str | None = None
    stations: list[ForecastStation] = Field(default_factory=list)


class StableEtaResponse(BaseModel):
    train_number: str
    current_eta: str | None = None
    previous_eta: str | None = None
    change_minutes: float | None = None
    eta_range: dict[str, Any] | None = None
    stability: str | None = None
    reliability: str | None = None
    generated_at: str | None = None


class ExplanationResponse(BaseModel):
    train_number: str
    current_delay_minutes: float | None = None
    predicted_additional_delay_minutes: float | None = None
    expected_recovery_minutes: float | None = None
    predicted_final_delay_minutes: float | None = None
    likely_contributing_factors: list[str] = Field(default_factory=list)
    reliability: str | None = None
    confidence: str | None = None
    prediction_source: str | None = None
    weather_influence: str | None = None
    explanation: str | None = None


class RouteStop(BaseModel):
    station_code: str | None = None
    station_name: str | None = None
    sequence: int | float | None = None
    day_offset: int | float | None = None
    scheduled_arrival: str | None = None
    scheduled_departure: str | None = None
    halt_minutes: float | None = None
    latitude: float | None = None
    longitude: float | None = None


class RouteResponse(BaseModel):
    train_number: str
    train_name: str | None = None
    source_station_code: str | None = None
    destination_station_code: str | None = None
    runs_days: str | None = None
    stops: list[RouteStop] = Field(default_factory=list)


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    reason: str | None = None
    reason_code: str | None = None
    current_train_number: str | None = None
    connecting_train_number: str | None = None
    connection_station: StationReference | str | None = None
    predicted_arrival: str | None = None
    connecting_departure: str | None = None
    minimum_transfer_minutes: float | None = None
    connection_time_minutes: float | None = None
    connection_margin_minutes: float | None = None
    risk: str | None = None
    recommendation: str | None = None
