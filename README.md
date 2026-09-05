# RailETA

RailETA is a real-data-only ETA forecasting platform for Indian Railways
coaching trains (SIH26028). The application keeps the existing React/Vite and
MapLibre frontend and exposes a Python/FastAPI backend.

## Stack

- Frontend: React 19, Vite, Tailwind CSS, shadcn/ui, MapLibre GL
- Backend: Python, FastAPI, Uvicorn
- Database: SQLite
- Live railway data: RailRadar API
- Historical railway data: RailKit Train History API
- Weather: Open-Meteo Historical Archive and Forecast APIs
- ML: XGBoost Regressor, Pandas, NumPy, scikit-learn, joblib

## Data policy

No synthetic or demo rows are used in the production dataset. RailKit
responses and Open-Meteo responses are cached locally and are ignored by Git.
Secrets belong only in `backend/.env`; copy `backend/.env.example` and never
commit the resulting file.

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
```

Windows PowerShell equivalents:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

Add only your own keys to `backend/.env`:

```text
RAILKIT_API_KEY=
RAILKIT_MAX_MONTHLY_REQUESTS=0
RAILRADAR_API_KEY=
OPEN_METEO_HISTORICAL_URL=https://archive-api.open-meteo.com/v1/archive
OPEN_METEO_FORECAST_URL=https://api.open-meteo.com/v1/forecast
```

## Historical data pipeline

### Automatic data lifecycle and quota-aware history collection

The normal workflow uses the real timetable, station, processed event, weather
cache, SQLite, RailRadar, and Open-Meteo sources already present in the project.
It does not require a manually prepared dataset to start the local processing
steps. If the optional `journeys.csv` manifest is present, it is treated as an
explicit allow-list of already confirmed RailKit train/date pairs. If it is
absent, the pipeline makes zero RailKit requests and continues with the
available local artifacts. It never infers historical dates from a timetable,
uses synthetic journeys, or forces a refresh.

When a confirmed manifest is available, the normal workflow processes one pair
at a time, reuses permanent raw cache files, skips the persistent unavailable
ledger, stops before the configured safety buffer, then enriches weather,
rebuilds SQLite, and gates XGBoost training on 100 real usable sections.

```bash
python -m backend.ml.pipeline
```

The collection report is written to
`backend/ml/data/historical_data_collection_report.json`. It shows the
configured limit, requests used, estimated remaining requests, safety buffer,
successful/unavailable/failed/skipped pairs, the persistent no-history ledger,
and the approximate number of additional successful journeys needed. The
collector appends normalized records to
`backend/data/processed/running_events.csv` through the existing
de-duplicating merge. The lower-level collector remains available as
`python -m backend.ml.ingestion.batch`, but it does not run post-processing.

1. If confirmed RailKit history is already cached or listed in the optional
   manifest, the collector cache-checks `backend/ml/data/raw/railkit/` and
   updates the event-level `backend/data/processed/running_events.csv`. A
   positive `RAILKIT_MAX_MONTHLY_REQUESTS` value is required before a new
   request is reserved. Repeating a cached train/date does not use another
   request. No historical request is made by live inference.

2. Match historical Open-Meteo observations by station coordinates, journey
   date, and nearest hourly event time:

   ```bash
   python3 -m backend.ml.ingestion.weather
   ```

   This writes `historical_weather.csv`, enriches the event CSV with the
   weather variables, and writes a quality report under `backend/ml/data/`.
   Events without genuine coordinates or timestamps remain unmatched.

3. Build or update SQLite:

   ```bash
   python3 backend/scripts/build_database.py
   ```

## Training

The trainer creates section rows for current station A → next station B. The
target is B's real arrival delay. It uses chronological journey-date splits;
rows from a later journey cannot influence earlier historical aggregates.

```bash
python3 -m backend.ml.train
```

It evaluates the current-departure-delay baseline against railway-only and
railway-plus-weather XGBoost variants. Artifacts are generated under
`backend/ml/models/` only after real labels are available:

- `eta_pipeline.joblib`
- `eta_railway_only.joblib`
- `eta_weather_aware.joblib`
- `feature_schema.json`
- `model_metadata.json`
- `metrics.json`
- `feature_importance.json`
- `historical_feature_store.csv`

The trainer refuses to claim success when event labels, dates, or partitions
are missing. Weather is never silently changed to “clear”.

### Data cleanup policy

The pipeline preserves runtime inputs and reproducibility artifacts: processed
datasets, the SQLite database, model artifacts, source metadata, permanent
provider caches, quota ledgers, unavailable-pair ledgers, and reports. Only
verified obsolete duplicates or temporary files may be removed after checking
that no application or pipeline code references them. Live request responses
are not stored as untracked debug exports.

## Runtime

Start the API from the repository root:

```bash
python3 -m uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Endpoints:

- `GET /api/v1/health`
- `GET /api/v1/trains`
- `GET /api/v1/trains/{train_number}`
- `GET /api/v1/trains/{train_number}/live`
- `GET /api/v1/trains/{train_number}/eta`
- `GET /api/v1/connections/risk?current_train_number={train_number}`
- `GET /api/v1/connections/debug?current_train_number={train_number}`

Additional public API adapters are available at:

- `GET /api/v1/trains/{train_number}/forecast`
- `GET /api/v1/trains/{train_number}/explanation`
- `GET /api/v1/trains/{train_number}/connections`
- `GET /api/v1/trains/{train_number}/route`

Developer key management uses the same SQLite database:

- `POST /api/v1/api-keys` with `{ "name": "My Application" }`
- `GET /api/v1/api-keys`
- `DELETE /api/v1/api-keys/{key_id}`

The plaintext key is returned only by the POST response. Listing returns only
metadata and a masked prefix. In local mode the page sends the configurable
`X-Account-ID` development identity because the current frontend has no
server-side login/session service; set `RAILETA_REQUIRE_ACCOUNT_AUTH=true` and
replace that development identity with the application's trusted account
identity before deployment.

When `RAILETA_REQUIRE_API_KEY=true`, send the configured
`RAILETA_PUBLIC_API_KEY` in the `X-API-Key` header. Local development leaves
this disabled by default so the existing frontend continues to work. The
lightweight in-memory limiter is configured with
`RAILETA_RATE_LIMIT_PER_MINUTE`; `0` disables it for controlled local tests.
Every API response includes an `X-Request-ID`. Errors use the JSON shape
`{"error":{"code":"...","message":"...","request_id":"..."}}`.

FastAPI's generated documentation is available at `/docs` and includes the
public API-key security scheme, parameters, response models, and endpoint
descriptions.

The ETA endpoint calls RailRadar and Open-Meteo Forecast only. It never calls
RailKit during a passenger or authority search. If no trained artifact exists,
it returns an explicit unavailable response rather than a fabricated ETA.

The connection-risk endpoint accepts an optional
`connecting_train_number`. When omitted, it automatically evaluates real
outgoing timetable services at every remaining predicted route station using
the shared predicted arrival. It returns `No connecting journey detected` when
the local timetable has no usable onward service.

The debug endpoint evaluates every remaining predicted station and reports
the real outgoing timetable rows searched at each station, candidate counts,
time/transfer filtering, and non-sensitive rejection reasons. It is intended
for development diagnostics, not as a replacement for the passenger response.

Start the frontend separately:

```bash
cd frontend
npm install
npm run dev
```

## Known V1 limitations

The model excludes signal aspects, official congestion, temporary speed
restrictions, maintenance blocks, track occupancy, preceding-train history,
crew/loco causes, and other operational fields until genuine historical feeds
for them are provided. These must not be fabricated.
