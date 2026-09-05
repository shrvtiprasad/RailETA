"""
RailETA Phase 1 — SQLite schema.

All tables mirror ONLY fields that exist in source data (NTES via railpull,
OpenStreetMap, RailKit Train History, and Open-Meteo historical weather),
plus a small set of explicitly-documented provenance columns
(data_source, source_url, collected_at, coordinate_source).

KNOWN GAP: railpull's stations.csv export provides only station code + name
(coordinates are blank until the optional OSM geocoding step runs). It does
NOT provide `state` or `zone`. Those two columns are kept in this schema
because the project spec asked for them, but they will be NULL unless you
join in a separately-sourced, documented station-to-zone reference table
later — never guessed or inferred here.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trains (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number            TEXT NOT NULL UNIQUE,
    train_name              TEXT NOT NULL,
    train_type              TEXT,               -- NTES code, e.g. VNDB, RAJ, SHT, DRNT, SUF, MEX, EXP
    source_station_code     TEXT,
    destination_station_code TEXT,
    distance_km             REAL,
    runs_days               TEXT,               -- "Daily" or "Mon,Wed,Fri" (railpull export.py derivation)
    data_source             TEXT NOT NULL,
    source_url              TEXT,
    collected_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    station_code        TEXT NOT NULL UNIQUE,
    station_name        TEXT NOT NULL,
    state               TEXT,               -- NULL unless a separately-sourced mapping is joined in later
    zone                TEXT,               -- NULL unless a separately-sourced mapping is joined in later
    latitude            REAL,               -- NULL until OSM geocode step is run; never estimated
    longitude           REAL,
    coordinate_source   TEXT,               -- "OpenStreetMap" or NULL
    data_source         TEXT NOT NULL,
    collected_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS train_stops (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number            TEXT NOT NULL,
    station_code            TEXT NOT NULL,
    sequence                INTEGER NOT NULL,
    day_offset              INTEGER,
    arrival_time            TEXT,
    departure_time          TEXT,
    halt_minutes            INTEGER,
    distance_from_source    REAL,
    FOREIGN KEY (train_number) REFERENCES trains(train_number),
    FOREIGN KEY (station_code) REFERENCES stations(station_code)
);

CREATE TABLE IF NOT EXISTS historical_delays (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number                TEXT NOT NULL,
    station_code                TEXT,
    average_delay_minutes       REAL,
    punctuality_percentage      REAL,
    delay_severity               TEXT,
    scraped_at                  TEXT,
    source_url                  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stops_train ON train_stops(train_number);
CREATE INDEX IF NOT EXISTS idx_stops_station ON train_stops(station_code);
CREATE INDEX IF NOT EXISTS idx_delays_train ON historical_delays(train_number);
CREATE INDEX IF NOT EXISTS idx_delays_station ON historical_delays(station_code);

CREATE TABLE IF NOT EXISTS historical_journeys (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number             TEXT NOT NULL,
    journey_date             TEXT NOT NULL,
    train_name               TEXT,
    train_type               TEXT,
    source_station_code      TEXT,
    destination_station_code TEXT,
    data_source              TEXT NOT NULL,
    collected_at             TEXT NOT NULL,
    raw_cache_path           TEXT,
    UNIQUE(train_number, journey_date)
);

CREATE TABLE IF NOT EXISTS running_events (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    journey_id               INTEGER,
    train_number             TEXT NOT NULL,
    journey_date             TEXT NOT NULL,
    station_code             TEXT NOT NULL,
    station_name             TEXT,
    station_sequence         INTEGER NOT NULL,
    distance_from_origin     REAL,
    scheduled_arrival        TEXT,
    actual_arrival           TEXT,
    arrival_delay_minutes    REAL,
    scheduled_departure      TEXT,
    actual_departure         TEXT,
    departure_delay_minutes  REAL,
    platform                 TEXT,
    data_source              TEXT NOT NULL,
    collected_at             TEXT NOT NULL,
    FOREIGN KEY (journey_id) REFERENCES historical_journeys(id),
    UNIQUE(train_number, journey_date, station_code, station_sequence)
);

CREATE TABLE IF NOT EXISTS historical_weather (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp                TEXT NOT NULL,
    latitude                REAL NOT NULL,
    longitude               REAL NOT NULL,
    station_code             TEXT,
    temperature_2m          REAL,
    relative_humidity_2m    REAL,
    precipitation           REAL,
    rain                     REAL,
    wind_speed_10m           REAL,
    weather_code             REAL,
    data_source              TEXT NOT NULL,
    collected_at             TEXT NOT NULL,
    UNIQUE(timestamp, latitude, longitude, station_code)
);

CREATE INDEX IF NOT EXISTS idx_history_train_date ON historical_journeys(train_number, journey_date);
CREATE INDEX IF NOT EXISTS idx_events_train_date ON running_events(train_number, journey_date);
CREATE INDEX IF NOT EXISTS idx_events_station ON running_events(station_code);
CREATE INDEX IF NOT EXISTS idx_weather_station_time ON historical_weather(station_code, timestamp);

CREATE TABLE IF NOT EXISTS prediction_snapshots (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    train_number             TEXT NOT NULL,
    predicted_at             TEXT NOT NULL,
    station_code             TEXT,
    station_name             TEXT,
    predicted_eta            TEXT NOT NULL,
    predicted_delay_minutes  REAL,
    confidence               TEXT,
    current_delay_minutes    REAL,
    data_quality              TEXT,
    data_source              TEXT NOT NULL DEFAULT 'RailRadar + RailETA model'
);

CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_train_time
    ON prediction_snapshots(train_number, predicted_at);

CREATE TABLE IF NOT EXISTS api_keys (
    id            TEXT PRIMARY KEY,
    account_id    TEXT NOT NULL,
    name          TEXT NOT NULL,
    key_hash      TEXT NOT NULL UNIQUE,
    key_prefix    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT,
    revoked_at    TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'revoked'))
);

CREATE INDEX IF NOT EXISTS idx_api_keys_account ON api_keys(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
"""
