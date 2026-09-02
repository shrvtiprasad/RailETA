"""
RailETA Phase 1 — SQLite schema.

All tables mirror ONLY fields that exist in source data (NTES via railpull,
OpenStreetMap, and the ETrain.info-derived Kaggle historical delay dataset),
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
"""
