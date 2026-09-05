# RailETA ML pipeline

This directory implements the real-data-only XGBoost pipeline for SIH26028.

## Required historical railway data

The training input is:

```text
backend/data/processed/running_events.csv
```

Required columns:

```text
train_number,journey_date,station_code,sequence,scheduled_arrival,actual_arrival
```

Each row is one real station event from one completed journey. Scheduled and
actual timestamps are required to create genuine labels. The builder derives
one section row for station A → station B, using B's arrival delay as the
target. It does not use B's actual arrival, departure, or delay as an input.

## RailKit ingestion

RailKit is called only by an explicit, cache-first command. The API key belongs
only in the ignored `backend/.env` file, and a positive monthly safety limit is
required before a new request is reserved.

```bash
python3 -m backend.ml.ingestion.railkit --train 12301 --date 11-06-2026
```

Successful responses are stored as:

```text
backend/ml/data/raw/railkit/<TRAIN_NUMBER>/<DD-MM-YYYY>.json
```

The normalized events are merged into `running_events.csv`. The same train and
date is read from cache on subsequent runs. RailKit is never called by the
live FastAPI ETA endpoint.

The batch pipeline reads `RAILKIT_MAX_MONTHLY_REQUESTS` from `backend/.env`.
If the provider dashboard gives a newer remaining-balance figure, set
`RAILKIT_PROVIDER_REMAINING_REQUESTS` to that number. The collector combines
the local reservation ledger with this provider snapshot conservatively, so an
older local ledger cannot make the available quota look larger than the
provider balance. `RAILKIT_SAFETY_BUFFER_REQUESTS` is held back from
collection.

Use the controlled coverage tool before collecting a larger sample:

```bash
python3 -m backend.ml.coverage --trains-file trains.txt --dates-file dates.txt
```

## Historical weather

After RailKit events exist and station coordinates are available, match
Open-Meteo Archive observations using the event station, date, and nearest
hour within three hours. The collector caches one response per coordinate/day
and preserves unmatched events as unmatched.

```bash
python3 -m backend.ml.ingestion.weather
```

The common weather variables are `temperature_2m`, `relative_humidity_2m`,
`precipitation`, `rain`, `wind_speed_10m`, and `weather_code`. Missing weather
remains missing; it is not changed to clear weather.

## Training and evaluation

```bash
python3 -m backend.ml.train
```

Training requires real labels, at least three journey dates, and non-empty
chronological train/validation/test partitions. It compares:

- the current departure-delay baseline;
- railway-only XGBoost;
- railway-plus-weather XGBoost.

Historical aggregates are calculated by journey date and shifted so a journey
cannot use its own or a later label. The untouched test partition is used only
for final comparison. Artifacts are generated under `backend/ml/models/`:

```text
eta_pipeline.joblib
eta_railway_only.joblib
eta_weather_aware.joblib
feature_schema.json
model_metadata.json
metrics.json
feature_importance.json
historical_feature_store.csv
```

The model predicts arrival delay in minutes for upcoming sections. Reliability
is an application status based on data completeness and model context; it is
not presented as a statistical confidence interval.
