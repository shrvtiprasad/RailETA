# RailETA — Data Sources (Phase 1)

Status: the repository contains the real extracted public timetable and
station-coordinate files listed below. RailKit event history and historical
weather remain opt-in inputs and have not been collected in this snapshot.

## 1. Static timetable data
- **Source:** National Train Enquiry System (NTES), enquiry.indianrail.gov.in
- **Extraction:** [`railpull`](https://github.com/shwetankg07/railpull) (MIT), via `ntes/crawl.py` + `transform/export.py`
- **Status:** unofficial extraction from a public government service. No affiliation with Indian Railways, CRIS, IRCTC, or NTES.
- **Fields copied verbatim from railpull's export:** number, name, type, type_label, runs_days, source_code, source, dest_code, destination, distance_km, travel_time, num_stops (trains.csv); train_number, seq, station_code, station_name, day, arrival, departure, halt_min, distance_km (stops.csv); code, name (stations.csv).
- **Fields derived upstream (by railpull, not by us):** `runs_days` is folded from NTES's raw list of upcoming run dates; `type_label` is a lookup from NTES's terse type code.
- **Selection performed by us:** `process_timetable.py` picks ~100–300 trains favoring Vande Bharat/Rajdhani/Shatabdi/Duronto/Superfast/Express types, spread across train-number first-digit buckets as a real-data-only proxy for geographic spread. This is a *selection*, not a data-generation step — every row already existed in railpull's output.

## 2. Station coordinates
- **Source:** OpenStreetMap, via railpull's optional `osm/geocode_stations.mjs` step, matching stations by official code against an OSM India extract.
- **License:** © OpenStreetMap contributors, ODbL.
- **Rule:** if this step isn't run, `latitude`/`longitude` stay NULL in the DB and the station is listed under `missing_coordinates` in the validation report. Never estimated.

## 3. Station state/zone
- **Not available from railpull.** Its `stations.csv` only has `code` and `name`. `state`/`zone` columns exist in our schema per the original spec but will be NULL until you supply a separately-sourced, documented zone-mapping table — never inferred or guessed here.

## 4. Historical delay data
- **Source:** "Indian Railways Train Delays Dataset 2025" on Kaggle (scraped from ETrain.info): https://www.kaggle.com/datasets/naijilaji/indian-railways-passenger-train-delays-dataset
- **Status:** third-party scrape, not official. Used only for historical/statistical features.
- **Access:** this source is optional and is not fetched automatically because
  it requires authenticated access. If an already-processed file exists, the
  pipeline uses it; if it is absent, the application reports that historical
  aggregate delay data is unavailable and continues with the other real
  sources. No user-provided dataset is required to run the local application.
- **Transformations:** `process_delays.py` maps whatever columns actually exist in the downloaded file onto our schema; missing targets are left NULL.

### ML training requirement
The aggregated `historical_delays.csv` schema is not, by itself, sufficient for station-level ETA training because it does not contain a real scheduled/actual timestamp pair for each train run. The XGBoost pipeline therefore expects a separate, real event-level file at `backend/data/processed/running_events.csv` with `train_number`, `journey_date`, `station_code`, `sequence`, `scheduled_arrival`, and `actual_arrival`. RailKit is the planned source for that file. Training stops when the file is absent or lacks usable labels; no rows are fabricated.

### RailKit history ingestion
- **Source:** RailKit's `getTrainHistory(trainNumber, journeyDate)` SDK method: https://railkit.in/docs/train-history
- **Purpose:** obtains completed, station-level scheduled/actual arrival events and provider-reported stop delays for real journeys. The model target is recomputed from scheduled and actual timestamps; the provider delay field is retained only for audit.
- **Access:** the repository includes a Node SDK bridge because RailKit documents a typed Node.js SDK. The Python importer calls it only through an explicit command, never during ordinary model training or every frontend request.
- **Quota controls:** responses are cached under `backend/ml/data/raw/railkit/` and request reservations are recorded in the ignored `backend/data/railkit_usage.json`. A positive `RAILKIT_MAX_MONTHLY_REQUESTS` value must be set intentionally in `backend/.env`; the default is disabled (`0`).
- **Status:** integration code is committed, but no RailKit response or API key
  is committed. Cached responses and existing processed events are used
  automatically. New history collection remains explicitly opt-in through a
  confirmed manifest because the provider requires a real completed journey
  date; the system never guesses dates or blocks local processing when that
  manifest is absent.

## 5. Live train status (not used in Phase 1)
- **Source:** RailRadar API — https://railradar.in/docs/live-train-status. Reserved for a later phase.

## Join keys
`train_number` and `station_code` are the canonical join keys across all sources. Names are never used for joining. Unmatched keys are reported in `validation_report.json`, never silently coerced.

## Automatic connection risk
Connection candidates are derived only from the existing SQLite timetable
(`trains` + `train_stops`). The endpoint does not call RailKit or invent
outgoing services. By default it uses a documented 10-minute minimum transfer
assumption (`RAILETA_DEFAULT_MINIMUM_TRANSFER_MINUTES`), with optional
station-specific overrides in `RAILETA_STATION_TRANSFER_MINUTES_JSON`.
`RAILETA_CONNECTION_MEDIUM_MARGIN_MINUTES` controls the small-positive-margin
MEDIUM band. If no real onward timetable service has usable times, the API
returns `No connecting journey detected`. The automatic search checks every
remaining predicted station, and the debug endpoint reports the exact station
rows and rejection reasons.
