from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contract import DataUnavailableError, validate_event_columns


CATEGORICAL_FEATURES = [
    "train_number",
    "train_type",
    "previous_station_code",
    "current_station_code",
    "next_station_code",
    "section_id",
    "source_station_code",
    "destination_station_code",
]

RAILWAY_NUMERIC_FEATURES = [
    "station_sequence",
    "day_offset",
    "section_distance_km",
    "scheduled_section_runtime_minutes",
    "scheduled_halt_duration_minutes",
    "actual_halt_duration_minutes",
    "current_arrival_delay_minutes",
    "current_departure_delay_minutes",
    "previous_arrival_delay_minutes",
    "previous_departure_delay_minutes",
    "historical_train_delay_mean",
    "historical_train_station_delay_mean",
    "historical_station_delay_mean",
    "historical_section_runtime_mean",
    "historical_section_runtime_median",
    "historical_section_runtime_std",
    "day_of_week",
    "month",
    "hour_of_day",
]

WEATHER_FEATURES = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "wind_speed_10m",
    "weather_code",
    "is_raining",
    "heavy_rain_indicator",
    "weather_severity",
    "fog_or_low_visibility_proxy",
    "high_wind_indicator",
]

NUMERIC_FEATURES = [*RAILWAY_NUMERIC_FEATURES, *WEATHER_FEATURES]
TARGET_COLUMN = "next_station_arrival_delay_minutes"
CONTEXT_COLUMNS = [
    "journey_date",
    "train_number",
    "current_station_code",
    "next_station_code",
    "next_station_name",
    "scheduled_next_arrival",
    "current_departure_delay_minutes",
    "target_arrival_time",
]


def _read_csv(path: Path, description: str) -> pd.DataFrame:
    if not path.exists():
        raise DataUnavailableError(f"DATA SOURCE ACCESS REQUIRED: {description} was not found at {path}.")
    try:
        return pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - pandas supplies the detail
        raise DataUnavailableError(f"Could not read {description} at {path}: {exc}") from exc


def _datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _join_train_metadata(frame: pd.DataFrame, trains: pd.DataFrame | None) -> pd.DataFrame:
    if trains is None or trains.empty:
        return frame
    source_column = "number" if "number" in trains.columns else "train_number"
    if source_column not in trains.columns:
        return frame
    columns = [source_column]
    for column in ("type", "train_type", "source_code", "source_station_code", "dest_code", "destination_station_code"):
        if column in trains.columns:
            columns.append(column)
    lookup = trains[columns].copy().rename(
        columns={
            source_column: "train_number",
            "type": "train_type",
            "source_code": "source_station_code",
            "dest_code": "destination_station_code",
        }
    )
    lookup["train_number"] = lookup["train_number"].astype(str).str.strip()
    lookup = lookup.drop_duplicates("train_number")
    return frame.merge(lookup, on="train_number", how="left", suffixes=("", "_lookup"))


def _join_schedule_metadata(frame: pd.DataFrame, stops: pd.DataFrame | None) -> pd.DataFrame:
    if stops is None or stops.empty:
        return frame
    if not {"train_number", "station_code"}.issubset(stops.columns):
        return frame
    lookup = stops.copy()
    lookup["train_number"] = lookup["train_number"].astype(str).str.strip()
    lookup["station_code"] = lookup["station_code"].astype(str).str.strip()
    if "seq" in lookup.columns:
        lookup["station_sequence"] = _number(lookup["seq"])
    if "station_sequence" not in frame.columns:
        frame["station_sequence"] = _number(frame["sequence"])
    merge_keys = ["train_number", "station_code"]
    if "station_sequence" in lookup.columns:
        merge_keys.append("station_sequence")
        frame["station_sequence"] = _number(frame["sequence"])
    columns = merge_keys + [column for column in ("day", "halt_min", "distance_km") if column in lookup.columns]
    lookup = lookup[columns].drop_duplicates(merge_keys)
    lookup = lookup.rename(
        columns={
            "day": "day_offset",
            "halt_min": "scheduled_halt_duration_minutes",
            "distance_km": "distance_from_origin_schedule",
        }
    )
    frame = frame.merge(lookup, on=merge_keys, how="left", suffixes=("", "_lookup"))
    if "distance_from_origin" not in frame.columns:
        frame["distance_from_origin"] = np.nan
    if "distance_from_origin_schedule" in frame.columns:
        frame["distance_from_origin"] = _number(frame["distance_from_origin"]).fillna(
            _number(frame["distance_from_origin_schedule"])
        )
    if "scheduled_halt_duration_minutes" not in frame.columns:
        frame["scheduled_halt_duration_minutes"] = np.nan
    return frame


def _past_journey_aggregate(
    frame: pd.DataFrame,
    group_columns: list[str],
    value_column: str,
    output_prefix: str,
) -> pd.DataFrame:
    usable = frame.dropna(subset=[value_column]).copy()
    if usable.empty:
        frame[output_prefix] = np.nan
        return frame
    summary = (
        usable.groupby([*group_columns, "journey_date"], dropna=False, as_index=False)[value_column]
        .agg(["mean", "median", "std"])
        .reset_index()
    )
    summary = summary.sort_values([*group_columns, "journey_date"])
    grouped = summary.groupby(group_columns, dropna=False)["mean"]
    summary[output_prefix] = grouped.transform(lambda values: values.shift(1).expanding().mean())
    if output_prefix.endswith("runtime_mean"):
        summary[output_prefix.replace("_mean", "_median")] = summary.groupby(group_columns, dropna=False)["median"].transform(lambda values: values.shift(1).expanding().mean())
        summary[output_prefix.replace("_mean", "_std")] = summary.groupby(group_columns, dropna=False)["std"].transform(lambda values: values.shift(1).expanding().mean())
    join_columns = [*group_columns, "journey_date"]
    value_columns = [output_prefix]
    for column in (output_prefix.replace("_mean", "_median"), output_prefix.replace("_mean", "_std")):
        if column in summary.columns:
            value_columns.append(column)
    return frame.merge(summary[join_columns + value_columns], on=join_columns, how="left")


def _weather_features(frame: pd.DataFrame) -> pd.DataFrame:
    for column in WEATHER_FEATURES[:6]:
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = _number(frame[column])
    code = frame["weather_code"]
    precipitation = frame["precipitation"]
    wind = frame["wind_speed_10m"]
    available = code.notna()
    frame["is_raining"] = np.where(available, code.between(51, 67) | code.between(80, 82) | code.between(95, 99), np.nan)
    frame["heavy_rain_indicator"] = np.where(
        code.notna() | precipitation.notna(),
        code.isin([65, 67, 82, 95, 96, 99]) | precipitation.ge(10),
        np.nan,
    )
    frame["weather_severity"] = np.where(
        code.notna(),
        np.select(
            [code.isin([45, 48]), code.between(51, 67), code.between(80, 82), code.between(95, 99)],
            [1, 2, 3, 4],
            default=0,
        ),
        np.nan,
    )
    frame["fog_or_low_visibility_proxy"] = np.where(code.notna(), code.isin([45, 48]), np.nan)
    frame["high_wind_indicator"] = np.where(wind.notna(), wind.ge(35), np.nan)
    return frame


def build_weather_feature_values(weather: dict[str, Any] | None = None) -> dict[str, float | None]:
    """Apply the same weather transformations to one live observation."""

    frame = _weather_features(pd.DataFrame([weather or {}]))
    values: dict[str, float | None] = {}
    for column in WEATHER_FEATURES:
        value = frame.iloc[0].get(column)
        values[column] = None if pd.isna(value) else float(value)
    return values


def build_training_frame(
    events: pd.DataFrame,
    trains: pd.DataFrame | None = None,
    stops: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one leakage-safe row per observed section A→B."""

    validate_event_columns(list(events.columns))
    frame = events.copy()
    frame["train_number"] = frame["train_number"].astype(str).str.strip()
    frame["station_code"] = frame["station_code"].astype(str).str.strip()
    frame["journey_date"] = pd.to_datetime(frame["journey_date"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d")
    for column in ("scheduled_arrival", "actual_arrival", "scheduled_departure", "actual_departure"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[f"{column}_dt"] = _datetime(frame[column])
    frame["sequence"] = _number(frame["sequence"])
    frame = frame.dropna(subset=["train_number", "station_code", "journey_date", "sequence", "scheduled_arrival_dt", "actual_arrival_dt"])
    if frame.empty:
        raise DataUnavailableError("DATA SOURCE ACCESS REQUIRED: no real scheduled/actual arrival pairs are available.")

    frame = _join_train_metadata(frame, trains)
    frame = _join_schedule_metadata(frame, stops)
    for column in ("train_type", "source_station_code", "destination_station_code"):
        if column not in frame.columns:
            frame[column] = np.nan
    for column in ("distance_from_origin", "day_offset", "scheduled_halt_duration_minutes"):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = _number(frame[column])

    grouping = ["train_number", "journey_date"]
    frame = frame.sort_values(grouping + ["sequence"]).reset_index(drop=True)
    frame["arrival_delay_minutes"] = (frame["actual_arrival_dt"] - frame["scheduled_arrival_dt"]).dt.total_seconds() / 60
    frame["departure_delay_minutes"] = (frame["actual_departure_dt"] - frame["scheduled_departure_dt"]).dt.total_seconds() / 60
    frame["current_arrival_delay_minutes"] = frame["arrival_delay_minutes"]
    frame["current_departure_delay_minutes"] = frame["departure_delay_minutes"]
    frame["previous_arrival_delay_minutes"] = frame.groupby(grouping)["arrival_delay_minutes"].shift(1)
    frame["previous_departure_delay_minutes"] = frame.groupby(grouping)["departure_delay_minutes"].shift(1)
    frame["previous_station_code"] = frame.groupby(grouping)["station_code"].shift(1)
    frame["current_station_code"] = frame["station_code"]
    frame["next_station_code"] = frame.groupby(grouping)["station_code"].shift(-1)
    frame["next_station_name"] = frame.groupby(grouping)["station_name"].shift(-1) if "station_name" in frame.columns else np.nan
    frame["next_scheduled_arrival_dt"] = frame.groupby(grouping)["scheduled_arrival_dt"].shift(-1)
    frame["next_actual_arrival_dt"] = frame.groupby(grouping)["actual_arrival_dt"].shift(-1)
    frame["next_station_delay"] = frame.groupby(grouping)["arrival_delay_minutes"].shift(-1)
    frame["target_arrival_time"] = frame["next_actual_arrival_dt"]

    scheduled_departure = frame["scheduled_departure_dt"].fillna(frame["scheduled_arrival_dt"])
    actual_departure = frame["actual_departure_dt"].fillna(frame["actual_arrival_dt"])
    frame["scheduled_section_runtime_minutes"] = (frame["next_scheduled_arrival_dt"] - scheduled_departure).dt.total_seconds() / 60
    frame["actual_section_runtime_minutes"] = (frame["next_actual_arrival_dt"] - actual_departure).dt.total_seconds() / 60
    frame["actual_halt_duration_minutes"] = (frame["actual_departure_dt"] - frame["actual_arrival_dt"]).dt.total_seconds() / 60
    frame["scheduled_halt_duration_minutes"] = frame["scheduled_halt_duration_minutes"].fillna(
        (frame["scheduled_departure_dt"] - frame["scheduled_arrival_dt"]).dt.total_seconds() / 60
    )
    frame["section_distance_km"] = frame.groupby(grouping)["distance_from_origin"].shift(-1) - frame["distance_from_origin"]
    frame["section_id"] = frame["current_station_code"].fillna("") + ":" + frame["next_station_code"].fillna("")
    scheduled_day = pd.to_datetime(frame["journey_date"])
    frame["day_of_week"] = scheduled_day.dt.dayofweek
    frame["month"] = scheduled_day.dt.month
    frame["hour_of_day"] = scheduled_departure.dt.hour

    frame = _past_journey_aggregate(frame, ["train_number"], "arrival_delay_minutes", "historical_train_delay_mean")
    frame = _past_journey_aggregate(frame, ["train_number", "current_station_code"], "arrival_delay_minutes", "historical_train_station_delay_mean")
    frame = _past_journey_aggregate(frame, ["current_station_code"], "arrival_delay_minutes", "historical_station_delay_mean")
    frame = _past_journey_aggregate(frame, ["section_id"], "actual_section_runtime_minutes", "historical_section_runtime_mean")
    frame = _weather_features(frame)

    frame[TARGET_COLUMN] = frame["next_station_delay"]
    frame["scheduled_next_arrival"] = frame["next_scheduled_arrival_dt"]
    frame = frame.dropna(subset=["next_station_code", TARGET_COLUMN]).copy()
    if frame.empty:
        raise DataUnavailableError("DATA SOURCE ACCESS REQUIRED: no complete consecutive station sections have real next-arrival labels.")

    output_columns = list(dict.fromkeys([*CONTEXT_COLUMNS, *CATEGORICAL_FEATURES, *NUMERIC_FEATURES, TARGET_COLUMN]))
    for column in output_columns:
        if column not in frame.columns:
            frame[column] = np.nan
    return frame[output_columns]


def load_training_frame(events_path: Path, trains_path: Path, stops_path: Path) -> pd.DataFrame:
    events = _read_csv(events_path, "event-level historical running data")
    trains = _read_csv(trains_path, "processed train data") if trains_path.exists() else None
    stops = _read_csv(stops_path, "processed stop data") if stops_path.exists() else None
    return build_training_frame(events, trains=trains, stops=stops)


def model_features(frame: pd.DataFrame, include_weather: bool = True) -> tuple[list[str], list[str]]:
    categorical = [column for column in CATEGORICAL_FEATURES if column in frame.columns]
    numeric_names = RAILWAY_NUMERIC_FEATURES + (WEATHER_FEATURES if include_weather else [])
    numeric = [column for column in numeric_names if column in frame.columns and frame[column].notna().any()]
    if not categorical and not numeric:
        raise DataUnavailableError("No usable feature columns were created from the real data.")
    return categorical, numeric
