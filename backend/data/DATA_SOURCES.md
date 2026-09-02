# RailETA — Data Sources (Phase 1)

Status: no real data loaded yet in this repo snapshot — populated once you
run the Windows extraction procedure and copy files in.

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
- **Access:** requires manual, authenticated download — place CSV(s) in `backend/data/raw/delays/`.
- **Transformations:** `process_delays.py` maps whatever columns actually exist in the downloaded file onto our schema; missing targets are left NULL.

## 5. Live train status (not used in Phase 1)
- **Source:** RailRadar API — https://railradar.in/docs/live-train-status. Reserved for a later phase.

## Join keys
`train_number` and `station_code` are the canonical join keys across all sources. Names are never used for joining. Unmatched keys are reported in `validation_report.json`, never silently coerced.
