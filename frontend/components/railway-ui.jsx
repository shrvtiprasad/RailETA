import React, { useEffect, useRef, useState } from 'react'

import {
  Map,
  Marker,
  Popup,
  NavigationControl,
  LngLatBounds,
  setWorkerUrl,
} from 'maplibre-gl'

import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'

import {
  HashRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useLocation,
} from 'react-router-dom'

import { ArrowRight } from 'lucide-react'

setWorkerUrl(workerUrl)

const API_BASE = 'http://127.0.0.1:8000/api/v1'

const DEMO_EMAIL = 'authority@raileta.demo'
const DEMO_PASSWORD = 'RailETA@123'

const passengerNav = [
  ['Overview', 'overview'],
  ['Stable ETA', 'stable-eta'],
  ['Delay Explanation', 'delay-explanation'],
  ['Connection Risk', 'connection-risk'],
]

const authorityNav = [
  ['Overview', ''],
  ['Delay Propagation', 'delay-propagation'],
  ['Delay & Recovery', 'delay-recovery'],
  ['Stable ETA', 'stable-eta'],
]

export function EmptyState({
  title = 'No prediction data available',
  detail = 'Waiting for backend data',
}) {
  return (
    <div className="empty-state">
      <span className="empty-mark">—</span>
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

/*
 * IST TIME FORMATTING
 */
function formatIST(isoString) {
  if (!isoString) return '—'
  try {
    const date = new Date(isoString)
    if (!Number.isFinite(date.getTime())) return '—'
    const ist = new Date(
      date.toLocaleString('en-US', {
        timeZone: 'Asia/Kolkata',
      })
    )
    const hours = ist.getHours()
    const mins = ist.getMinutes()
    const ampm = hours >= 12 ? 'PM' : 'AM'
    const h = hours % 12 || 12
    const m = String(mins).padStart(2, '0')
    const day = String(ist.getDate()).padStart(2, '0')
    const month = ist.toLocaleString('en-US', { month: 'short' })
    return `${day} ${month}, ${h}:${m} ${ampm} IST`
  } catch {
    return '—'
  }
}

function formatTimeIST(isoString) {
  if (!isoString) return '—'
  try {
    const date = new Date(isoString)
    if (!Number.isFinite(date.getTime())) return '—'
    const ist = new Date(
      date.toLocaleString('en-US', {
        timeZone: 'Asia/Kolkata',
      })
    )
    const hours = ist.getHours()
    const mins = ist.getMinutes()
    const ampm = hours >= 12 ? 'PM' : 'AM'
    const h = hours % 12 || 12
    const m = String(mins).padStart(2, '0')
    return `${h}:${m} ${ampm}`
  } catch {
    return '—'
  }
}

/*
 * DELAY FORMATTING
 */
function delayMinutes(scheduled, actual) {
  if (!scheduled || !actual) return null
  try {
    const s = new Date(scheduled)
    const a = new Date(actual)
    if (
      !Number.isFinite(s.getTime()) ||
      !Number.isFinite(a.getTime())
    )
      return null
    return Math.round((a - s) / 60000)
  } catch {
    return null
  }
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  })
}

function Header({
  authority = false,
  active = 'overview',
}) {
  const nav = authority ? authorityNav : passengerNav

  const base = authority
    ? '/authority-dashboard'
    : '/passenger-dashboard'

  return (
    <header className="dashboard-header passenger-nav">
      <Link className="brand" to={base}>
        <span className="brand-mark">
          <img src="/logo.png" alt="RailETA" />
        </span>

        <span>RailETA</span>
      </Link>

      <nav>
        {nav.map(([label, id]) =>
          authority ? (
            <NavLink
              key={label}
              end={!id}
              to={`${base}${id ? `/${id}` : ''}`}
              className={({ isActive }) =>
                isActive ? 'active' : ''
              }
            >
              {label}
            </NavLink>
          ) : (
            <a
              key={label}
              className={
                active === id ? 'active' : ''
              }
              href={`#${id}`}
              onClick={(event) => {
                event.preventDefault()
                scrollToSection(id)
              }}
            >
              {label}
            </a>
          )
        )}
      </nav>

      <Link
        className="exit-link"
        to={authority ? '/authority-login' : '/'}
      >
        {authority ? 'Sign out' : 'Back to home'}
      </Link>
    </header>
  )
}

/* =========================================================
   LIVE RAILWAY MAP
   ========================================================= */

function RailwayMap({ trainNumber, onLiveUpdate }) {
  const mapContainer = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)
  const stopMarkersRef = useRef([])
  const hasCenteredRef = useRef(false)

  const [liveData, setLiveData] = useState(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [mapError, setMapError] = useState('')

  /*
   * LIVE TRAIN DATA
   */
  useEffect(() => {
    if (!trainNumber) return

    let cancelled = false

    async function fetchLiveTrain() {
      try {
        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(
            trainNumber
          )}/live`
        )

        if (!response.ok) {
          throw new Error(
            `Live train request failed (${response.status})`
          )
        }

        const result = await response.json()

        if (cancelled) return

        const resolved = result.data ?? result
        setLiveData(resolved)
        setMapError('')

        if (onLiveUpdate) {
          onLiveUpdate(resolved)
        }
      } catch (error) {
        console.error('Live RailRadar error:', error)

        if (!cancelled) {
          setMapError(
            error.message ||
              'Could not load live train data.'
          )
        }
      }
    }

    fetchLiveTrain()

    const interval = setInterval(
      fetchLiveTrain,
      30000
    )

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [trainNumber])

  /*
   * INITIALIZE MAP
   */
  useEffect(() => {
    if (
      !mapContainer.current ||
      mapRef.current
    ) {
      return
    }

    const map = new Map({
      container: mapContainer.current,
      style:
        'https://tiles.openfreemap.org/styles/liberty',
      center: [78.45593, 25.641283],
      zoom: 6,
      attributionControl: true,
    })

    mapRef.current = map

    map.addControl(
      new NavigationControl(),
      'top-right'
    )

    map.on('load', () => {
      setMapLoaded(true)

      requestAnimationFrame(() => {
        map.resize()
      })
    })

    map.on('error', (event) => {
      console.error(
        'MapLibre error:',
        event?.error || event
      )
    })

    const handleResize = () => {
      map.resize()
    }

    window.addEventListener(
      'resize',
      handleResize
    )

    return () => {
      window.removeEventListener(
        'resize',
        handleResize
      )

      markerRef.current?.remove()
      markerRef.current = null

      stopMarkersRef.current.forEach(
        (marker) => marker.remove()
      )

      stopMarkersRef.current = []

      map.remove()
      mapRef.current = null

      setMapLoaded(false)
      hasCenteredRef.current = false
    }
  }, [])

  /*
   * LIVE TRAIN POSITION + ROUTE + STATIONS
   */
  useEffect(() => {
    const map = mapRef.current

    if (
      !map ||
      !mapLoaded ||
      !liveData
    ) {
      return
    }

    if (!map.isStyleLoaded()) {
      return
    }

    /*
     * ROUTE STATIONS
     */
    const routeStops = Array.isArray(
      liveData.route
    )
      ? liveData.route
      : liveData.route?.stops || []

    const validStops = routeStops
      .filter(
        (stop) =>
          stop?.lat != null &&
          stop?.lng != null
      )
      .sort(
        (a, b) =>
          Number(a.sequence ?? 0) -
          Number(b.sequence ?? 0)
      )

    /*
     * =========================================================
     * TRAIN POINTER
     * =========================================================
     *
     * RailRadar may not provide:
     *
     * currentLocation.coordinates
     *
     * So first try that.
     *
     * If it isn't available, calculate the train position
     * between the current segment's two stations.
     */

    /*
     * Remove old train marker if any.
     */
    if (markerRef.current) {
      markerRef.current.remove()
      markerRef.current = null
    }

    /*
     * =========================================================
     * BLUE ROUTE
     * =========================================================
     */

    const fallbackCoordinates =
      validStops
        .map((stop) => [
          Number(stop.lng),
          Number(stop.lat),
        ])
        .filter(
          ([lng, lat]) =>
            Number.isFinite(lng) &&
            Number.isFinite(lat)
        )

    let routeGeometry = null

    if (
      fallbackCoordinates.length > 1
    ) {
      routeGeometry = {
        type: 'LineString',
        coordinates:
          fallbackCoordinates,
      }
    }

    if (routeGeometry) {
      const routeGeoJSON = {
        type: 'Feature',
        properties: {
          trainNumber:
            liveData.trainNumber ||
            trainNumber,
        },
        geometry: routeGeometry,
      }

      const existingSource =
        map.getSource(
          'train-route'
        )

      if (existingSource) {
        existingSource.setData(
          routeGeoJSON
        )
      } else {
        map.addSource(
          'train-route',
          {
            type: 'geojson',
            data: routeGeoJSON,
          }
        )
      }

      if (
        !map.getLayer(
          'train-route-line'
        )
      ) {
        map.addLayer({
          id: 'train-route-line',
          type: 'line',
          source: 'train-route',
          layout: {
            'line-join': 'round',
            'line-cap': 'round',
          },
          paint: {
            'line-color':
              '#4c7090',
            'line-width': 5,
            'line-opacity': 0.9,
          },
        })
      }

      /*
       * Fit map to route once.
       */
      if (
        !hasCenteredRef.current
      ) {
        const bounds =
          new LngLatBounds()

        fallbackCoordinates.forEach(
          ([lng, lat]) => {
            bounds.extend([
              lng,
              lat,
            ])
          }
        )

        if (!bounds.isEmpty()) {
          map.fitBounds(
            bounds,
            {
              padding: 60,
              duration: 1200,
              maxZoom: 8,
            }
          )

          hasCenteredRef.current =
            true
        }
      }
    }

    /*
     * =========================================================
     * STATION MARKERS
     * =========================================================
     */

    stopMarkersRef.current.forEach(
      (marker) =>
        marker.remove()
    )

    stopMarkersRef.current = []

    /*
     * Only place markers for actual scheduled
     * halts (isHalt=true), not passing stations.
     * The blue route line covers all route
     * stations; markers distinguish halts.
     */

    const haltsOnly =
      validStops.filter(
        (stop) => stop.isHalt !== false
      )

    /*
     * Find the upcoming HALT station
     * (first halt with status 'upcoming'
     * or 'approaching' or 'arriving').
     * Must search haltsOnly, not validStops,
     * because validStops includes passing
     * stations that don't get markers.
     */
    let upcomingStop = null

    for (let i = 0; i < haltsOnly.length; i++) {
      const s = haltsOnly[i]
      const st = (
        s.status || ''
      ).toLowerCase()

      if (
        st === 'upcoming' ||
        st === 'approaching' ||
        st === 'arriving'
      ) {
        upcomingStop = s
        break
      }
    }

    haltsOnly.forEach((stop) => {
      const lat = Number(
        stop.lat
      )

      const lng = Number(
        stop.lng
      )

      if (
        !Number.isFinite(lat) ||
        !Number.isFinite(lng)
      ) {
        return
      }

      const isUpcoming =
        upcomingStop &&
        stop.stationCode ===
          upcomingStop.stationCode

      const stopElement =
        document.createElement('div')

      stopElement.style.width =
        isUpcoming ? '22px' : '12px'

      stopElement.style.height =
        isUpcoming ? '22px' : '12px'

      stopElement.style.borderRadius =
        '50%'

      stopElement.style.background =
        isUpcoming ? '#4c7090' : '#fbfaf7'

      stopElement.style.border =
        isUpcoming
          ? '3px solid #fff'
          : '2px solid #4c7090'

      stopElement.style.boxShadow =
        isUpcoming
          ? '0 0 0 4px rgba(76,112,144,0.5), 0 2px 12px rgba(76,112,144,0.6)'
          : '0 2px 6px rgba(38, 51, 58, 0.2)'

      stopElement.style.cursor =
        'pointer'

      stopElement.style.zIndex =
        isUpcoming ? '10' : '1'

      const marker =
        new Marker({
          element:
            stopElement,
          anchor:
            'center',
        })
          .setLngLat([
            lng,
            lat,
          ])
          .addTo(map)

      marker.setPopup(
        new Popup({
          offset: 12,
        }).setHTML(`
          <div style="
            font-family: system-ui, sans-serif;
            min-width: 150px;
            padding: 2px;
          ">
            ${
              isUpcoming
                ? '<span style="display:block;background:#4c7090;color:#fbfaf7;text-align:center;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:700;letter-spacing:0.06em;margin-bottom:6px;">NEXT STATION</span>'
                : ''
            }
            <strong style="
              display: block;
              font-size: 14px;
              color: #26333a;
              margin-bottom: 3px;
            ">
              ${
                stop.stationName ||
                'Station'
              }
            </strong>

            <span style="
              display: block;
              font-size: 12px;
              color: #66737a;
            ">
              ${
                stop.stationCode ||
                ''
              }
            </span>

            ${
              stop.status
                ? `
                  <span style="
                    display: block;
                    margin-top: 5px;
                    font-size: 11px;
                    text-transform: capitalize;
                    color: #4c7090;
                  ">
                    ${stop.status}
                  </span>
                `
                : ''
            }
          </div>
        `)
      )

      stopMarkersRef.current.push(
        marker
      )
    })
  }, [
    liveData,
    mapLoaded,
    trainNumber,
  ])

  return (
    <section className="map-panel">
      <div className="section-kicker">
        Live context
      </div>

      <h2>Railway map</h2>

      <div
        ref={mapContainer}
        className="map-empty"
        style={{
          minHeight: '480px',
          height: '480px',
          marginTop: '20px',
          display: 'block',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {!liveData &&
          !mapError && (
            <div
              style={{
                position:
                  'absolute',
                inset: 0,
                display: 'grid',
                placeItems:
                  'center',
                pointerEvents:
                  'none',
                zIndex: 5,
                background:
                  'rgba(231, 226, 217, 0.72)',
              }}
            >
              <div
                style={{
                  background:
                    'rgba(251, 250, 247, 0.94)',
                  border:
                    '1px solid #d1c6b8',
                  borderRadius:
                    '12px',
                  padding:
                    '12px 16px',
                  color:
                    '#26333a',
                  fontSize:
                    '14px',
                }}
              >
                Loading live railway
                data...
              </div>
            </div>
          )}

        {mapError && (
          <div
            style={{
              position:
                'absolute',
              left: '16px',
              right: '16px',
              bottom: '16px',
              zIndex: 10,
              background:
                'rgba(251, 250, 247, 0.96)',
              border:
                '1px solid #d1c6b8',
              borderRadius:
                '12px',
              padding:
                '12px 14px',
              display: 'flex',
              flexDirection:
                'column',
              gap: '4px',
              boxShadow:
                '0 4px 14px rgba(38, 51, 58, 0.12)',
            }}
          >
            <strong>
              Unable to load live
              position
            </strong>

            <span
              style={{
                fontSize:
                  '13px',
                opacity: 0.75,
              }}
            >
              {mapError}
            </span>
          </div>
        )}
      </div>
    </section>
  )
}
/* =========================================================
   FIELD LIST
   ========================================================= */

function FieldList({ fields }) {
  return (
    <div className="eta-list">
      {fields.map((label) => (
        <div className="eta-row" key={label}>
          <span>{label}</span>
          <b>—</b>
        </div>
      ))}
    </div>
  )
}

/* =========================================================
   STATION / TRAIN INFORMATION
   ========================================================= */

function StationEtaPanel({ train }) {
  if (!train) {
    return (
      <section className="eta-panel">
        <div className="section-kicker">
          Station-wise ETA
        </div>

        <h2>Upcoming movement</h2>

        <FieldList
          fields={[
            'Upcoming station',
            'Predicted arrival',
            'ETA range',
            'Delay',
            'Reliability',
          ]}
        />
      </section>
    )
  }

  return (
    <section className="eta-panel">
      <div className="section-kicker">
        Train information
      </div>

      <h2>{train.train_name}</h2>

      <div className="eta-list">
        <div className="eta-row">
          <span>Train number</span>
          <b>{train.train_number}</b>
        </div>

        <div className="eta-row">
          <span>Train type</span>
          <b>{train.train_type || '—'}</b>
        </div>

        <div className="eta-row">
          <span>Source</span>
          <b>
            {train.source_station_code || '—'}
          </b>
        </div>

        <div className="eta-row">
          <span>Destination</span>
          <b>
            {train.destination_station_code ||
              '—'}
          </b>
        </div>

        <div className="eta-row">
          <span>Distance</span>
          <b>
            {train.distance_km
              ? `${train.distance_km} km`
              : '—'}
          </b>
        </div>

        <div className="eta-row">
          <span>Runs</span>
          <b>{train.runs_days || '—'}</b>
        </div>
      </div>
    </section>
  )
}

/* =========================================================
   FEATURE CARD
   ========================================================= */

function FeatureCard({
  title,
  description,
  label,
  href,
}) {
  const target = href.replace('#', '')

  return (
    <a
      className="feature-card"
      href={href}
      onClick={(event) => {
        event.preventDefault()
        scrollToSection(target)
      }}
    >
      <span className="section-kicker">
        Passenger feature
      </span>

      <h3>{title}</h3>

      <p>{description}</p>

      <span className="feature-link">
        {label}
        <ArrowRight size={16} />
      </span>
    </a>
  )
}

/* =========================================================
   PASSENGER FEATURE SECTIONS
   ========================================================= */

function FeatureSections() {
  return (
    <>
      <section
        id="stable-eta"
        className="passenger-section"
      >
        <span className="section-kicker">
          Passenger feature
        </span>

        <h2>Stable Passenger ETA</h2>

        <p className="feature-lede">
          Prevents unnecessary minute-by-minute ETA
          fluctuations and shows only meaningful changes.
        </p>

        <div className="feature-panel">
          <FieldList
            fields={[
              'Current ETA',
              'ETA Range',
              'Previous ETA',
              'Change',
              'Stability',
              'Reliability',
            ]}
          />
        </div>
      </section>

      <section
        id="delay-explanation"
        className="passenger-section"
      >
        <span className="section-kicker">
          Passenger feature
        </span>

        <h2>Why is my train delayed?</h2>

        <p className="feature-lede">
          Provides passengers with clear, plain-language
          reasons for delays and expected recovery.
        </p>

        <div className="feature-panel">
          <FieldList
            fields={[
              'Current Delay',
              'Why is my train delayed?',
              'Expected Recovery',
              'Current Status',
            ]}
          />

          <div className="plain-language">
            <strong>
              Waiting for prediction
            </strong>

            <span>
              Simple delay context will appear when
              backend data is available.
            </span>
          </div>
        </div>
      </section>

      <section
        id="connection-risk"
        className="passenger-section"
      >
        <span className="section-kicker">
          Passenger feature
        </span>

        <h2>Connection Risk Alerts</h2>

        <p className="feature-lede">
          Warns passengers when predicted delays may
          affect connecting trains or onward journeys.
        </p>

        <div className="feature-panel">
          <FieldList
            fields={[
              'Connecting Journey',
              'Predicted Arrival',
              'Connection Time',
              'Risk',
              'Recommendation',
            ]}
          />
        </div>
      </section>
    </>
  )
}

/* =========================================================
   SCHEDULE STOP ROW
   ========================================================= */

function ScheduleStopRow({ stop, isNextStation }) {
  const {
    station_code,
    station_name,
    sequence,
    arrival_time,
    departure_time,
    actual_arrival,
    actual_departure,
    delay_arrival,
    delay_departure,
    status,
  } = stop

  const isDeparted =
    status === 'departed' || status === 'passed'

  const isCurrent =
    status === 'at-station' ||
    status === 'arriving' ||
    status === 'approaching'

  const depDelay =
    delay_departure ??
    delayMinutes(departure_time, actual_departure)
  const arrDelay =
    delay_arrival ??
    delayMinutes(arrival_time, actual_arrival)

  const hasActualArr = !!actual_arrival
  const hasActualDep = !!actual_departure

  /*
   * Determine displayed arrival time.
   * If actual/predicted time exists from RailRadar,
   * show it (with scheduled crossed out if delayed).
   * Works for departed AND upcoming/current stations.
   */
  let displayArr = null
  let arrIsDelayed = false
  let arrIsEarly = false
  if (hasActualArr) {
    displayArr = formatTimeIST(actual_arrival)
    arrIsDelayed = (arrDelay ?? 0) > 0
    arrIsEarly = (arrDelay ?? 0) < 0
  } else if (arrival_time) {
    displayArr = formatTimeIST(arrival_time)
  }

  /*
   * Determine displayed departure time.
   * Same logic — use actual if available.
   */
  let displayDep = null
  let depIsDelayed = false
  let depIsEarly = false
  if (hasActualDep) {
    displayDep = formatTimeIST(actual_departure)
    depIsDelayed = (depDelay ?? 0) > 0
    depIsEarly = (depDelay ?? 0) < 0
  } else if (departure_time) {
    displayDep = formatTimeIST(departure_time)
  }

  const scheduledArr = formatTimeIST(arrival_time)
  const scheduledDep = formatTimeIST(departure_time)

  const rowBg = isNextStation
    ? 'rgba(76,112,144,0.08)'
    : isCurrent
    ? 'rgba(232,201,161,0.15)'
    : 'transparent'

  const rowBorder = isNextStation
    ? '2px solid rgba(76,112,144,0.35)'
    : undefined

  const rowShadow = isNextStation
    ? '0 0 12px rgba(76,112,144,0.18), inset 0 0 8px rgba(76,112,144,0.06)'
    : undefined

  return (
    <div
      className="eta-row"
      key={`${station_code}-${sequence}`}
      style={{
        background: rowBg,
        border: rowBorder,
        borderRadius: isNextStation ? '10px' : undefined,
        boxShadow: rowShadow,
        padding: isNextStation ? '14px 16px' : undefined,
      }}
    >
      {/* LEFT: Station info */}
      <span style={{minWidth:0, flex:'1 1 auto'}}>
        <span style={{
          fontWeight: 700,
          color: isNextStation ? '#4c7090' : '#26333a',
          fontSize: isNextStation ? '15px' : '14px',
        }}>
          {sequence}. {station_code}
        </span>

        {station_name && (
          <span style={{
            color: '#66737a',
            fontSize: '12px',
            marginLeft: '6px',
          }}>
            {station_name}
          </span>
        )}

        {isNextStation && (
          <span style={{
            display: 'inline-block',
            marginLeft: '8px',
            padding: '1px 7px',
            background: '#4c7090',
            color: '#fbfaf7',
            borderRadius: '999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.04em',
            verticalAlign: 'middle',
          }}>
            NEXT
          </span>
        )}

        {isCurrent && !isNextStation && (
          <span style={{
            display: 'inline-block',
            marginLeft: '8px',
            padding: '1px 7px',
            background: '#e8c9a1',
            color: '#26333a',
            borderRadius: '999px',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.04em',
            verticalAlign: 'middle',
          }}>
            NOW
          </span>
        )}
      </span>

      {/* RIGHT: Times */}
      <span style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: '4px',
        minWidth: 0,
        flexShrink: 0,
      }}>
        {/* Arrival */}
        {displayArr && (
          <span style={{fontSize:'12px', lineHeight:'1.4'}}>
            <span style={{color:'#8a9399', fontSize:'10px'}}>Arr </span>
            {!hasActualArr && (
              <span style={{color:'#526066'}}>
                {scheduledArr}
              </span>
            )}
            {hasActualArr && (
              <>
                <span style={{
                  color:'#8a9399',
                  textDecoration: arrIsDelayed || arrIsEarly ? 'line-through' : 'none',
                  fontSize: '11px',
                }}>
                  {scheduledArr}
                </span>
                {' '}
                <span style={{
                  color: arrIsDelayed
                    ? '#dc5032'
                    : arrIsEarly
                    ? '#2d8a4e'
                    : '#2d8a4e',
                  fontWeight: 700,
                }}>
                  → {displayArr}
                </span>
              </>
            )}
            {arrIsDelayed && (
              <span style={{
                color:'#dc5032',
                fontWeight:700,
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                +{arrDelay}m
              </span>
            )}
            {arrIsEarly && (
              <span style={{
                color:'#2d8a4e',
                fontWeight:700,
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                {arrDelay}m
              </span>
            )}
            {!arrIsDelayed && !arrIsEarly && hasActualArr && (
              <span style={{
                color:'#2d8a4e',
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                ✓
              </span>
            )}
          </span>
        )}

        {/* Departure */}
        {displayDep && (
          <span style={{fontSize:'12px', lineHeight:'1.4'}}>
            <span style={{color:'#8a9399', fontSize:'10px'}}>Dep </span>
            {!hasActualDep && (
              <span style={{color:'#526066'}}>
                {scheduledDep}
              </span>
            )}
            {hasActualDep && (
              <>
                <span style={{
                  color:'#8a9399',
                  textDecoration: depIsDelayed || depIsEarly ? 'line-through' : 'none',
                  fontSize: '11px',
                }}>
                  {scheduledDep}
                </span>
                {' '}
                <span style={{
                  color: depIsDelayed
                    ? '#dc5032'
                    : depIsEarly
                    ? '#2d8a4e'
                    : '#2d8a4e',
                  fontWeight: 700,
                }}>
                  → {displayDep}
                </span>
              </>
            )}
            {depIsDelayed && (
              <span style={{
                color:'#dc5032',
                fontWeight:700,
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                +{depDelay}m
              </span>
            )}
            {depIsEarly && (
              <span style={{
                color:'#2d8a4e',
                fontWeight:700,
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                {depDelay}m
              </span>
            )}
            {!depIsDelayed && !depIsEarly && hasActualDep && (
              <span style={{
                color:'#2d8a4e',
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                ✓
              </span>
            )}
          </span>
        )}
      </span>
    </div>
  )
}

/* =========================================================
   PASSENGER DASHBOARD
   ========================================================= */

function PassengerDashboard() {
  const [active, setActive] = useState('overview')
  const [train, setTrain] = useState(null)
  const [stops, setStops] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [liveInfo, setLiveInfo] = useState(null)

  const location = useLocation()

  const params = new URLSearchParams(
    location.search
  )

  const trainNumber = params.get('train')

  /*
   * Track which passenger section is currently visible.
   */

  useEffect(() => {
    const sections = [
      'overview',
      'stable-eta',
      'delay-explanation',
      'connection-risk',
    ]
      .map((id) => document.getElementById(id))
      .filter(Boolean)

    const observer =
      new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter(
              (entry) => entry.isIntersecting
            )
            .sort(
              (a, b) =>
                b.intersectionRatio -
                a.intersectionRatio
            )[0]

          if (visible) {
            setActive(visible.target.id)
          }
        },
        {
          rootMargin:
            '-20% 0px -55% 0px',
          threshold: [0.1, 0.4, 0.8],
        }
      )

    sections.forEach((section) =>
      observer.observe(section)
    )

    return () => observer.disconnect()
  }, [])

  /*
   * Fetch train information from RailETA backend.
   */

  useEffect(() => {
    if (!trainNumber) {
      setLoading(false)
      setError('No train number was provided.')
      return
    }

    async function loadTrain() {
      setLoading(true)
      setError('')

      try {
        /*
         * First try the RailETA SQLite timetable.
         */

        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(
            trainNumber
          )}`
        )

        if (response.ok) {
          const data = await response.json()

          setTrain(data.train)
          setStops(data.stops || [])

          return
        }

        /*
         * If SQLite doesn't contain the train,
         * try the live RailRadar endpoint.
         */

        if (response.status === 404) {
          const liveResponse = await fetch(
            `${API_BASE}/trains/${encodeURIComponent(
              trainNumber
            )}/live`
          )

          if (!liveResponse.ok) {
            if (liveResponse.status === 404) {
              throw new Error(
                `Train ${trainNumber} was not found in the RailETA timetable or RailRadar live data.`
              )
            }

            throw new Error(
              `Live train request failed (${liveResponse.status})`
            )
          }

          const liveResult =
            await liveResponse.json()

          const liveData =
            liveResult.data ?? liveResult

          const t = liveData.train || {}

          const liveTrain = {
            train_number:
              t.number ||
              liveData.trainNumber ||
              trainNumber,

            train_name:
              t.name ||
              liveData.trainName ||
              `Train ${trainNumber}`,

            train_type:
              t.type ||
              liveData.trainType ||
              'Live tracking',

            source_station_code:
              t.source?.code ||
              '—',

            destination_station_code:
              t.destination?.code ||
              '—',

            distance_km:
              t.distance ||
              null,

            runs_days:
              Array.isArray(t.runDays)
                ? t.runDays.join(', ')
                : null,
          }

          /*
           * Populate stops from live route
           * when SQLite has none.
           */
          const liveRoute =
            Array.isArray(liveData.route)
              ? liveData.route
              : []

          /*
           * Only include actual halts
           * (isHalt=true), not passing stations.
           */
          const liveStops =
            liveRoute
              .filter((s) => s.isHalt)
              .map((s, i) => ({
                station_code:
                  s.stationCode || '—',
                station_name:
                  s.stationName || '',
                sequence:
                  s.sequence || i + 1,
                arrival_time:
                  s.scheduledArrival || null,
                departure_time:
                  s.scheduledDeparture || null,
                actual_arrival:
                  s.actualArrival || null,
                actual_departure:
                  s.actualDeparture || null,
                delay_arrival:
                  s.delayArrival ?? null,
                delay_departure:
                  s.delayDeparture ?? null,
                status:
                  s.status || 'upcoming',
              }))

          setTrain(liveTrain)
          setStops(liveStops)
          setError('')

          return
        }

        throw new Error(
          'Failed to fetch train data.'
        )
      } catch (err) {
        console.error(err)

        setTrain(null)
        setStops([])

        setError(
          err.message ||
            'Could not connect to the RailETA backend.'
        )
      } finally {
        setLoading(false)
      }
    }

    loadTrain()
  }, [trainNumber])



  /*
   * Derive liveInfo from RailwayMap's
   * shared liveData (no extra fetch).
   */

  function handleLiveUpdate(data) {
    if (!data) return

    const route =
      Array.isArray(data.route)
        ? data.route
        : []

    /*
     * Distinguish halts from passing stations.
     * isHalt=true  → actual scheduled stop
     * isHalt=false → train passes through
     */
    const halts =
      route.filter((s) => s.isHalt)

    const completedHalts =
      halts.filter(
        (s) =>
          s.status === 'departed' ||
          s.status === 'passed'
      ).length

    const remainingHalts =
      halts.filter(
        (s) =>
          s.status === 'upcoming' ||
          s.status === 'approaching' ||
          s.status === 'arriving'
      ).length

    const currentStop =
      route.find(
        (s) =>
          s.stationCode ===
            data.currentLocation?.stationCode
      )

    const nextUpcomingHalt =
      halts.find(
        (s) =>
          s.status === 'upcoming' ||
          s.status === 'approaching' ||
          s.status === 'arriving'
      )

    setLiveInfo({
      status: data.status,
      delayMinutes:
        data.delayMinutes || 0,
      currentStation:
        data.currentLocation?.stationCode ||
        null,
      currentStationName:
        currentStop?.stationName ||
        data.currentLocation?.stationCode ||
        null,
      currentSequence:
        data.currentLocation?.sequence,
      segmentProgress:
        data.currentLocation?.segmentProgress,
      speedKmh:
        data.currentLocation?.speedKmh,
      nextStation:
        data.nextHalt?.stationCode ||
        nextUpcomingHalt?.stationCode || null,
      nextStationName:
        data.nextHalt?.stationName ||
        nextUpcomingHalt?.stationName || null,
      totalRouteStations: route.length,
      totalStops: halts.length,
      completedStops: completedHalts,
      remainingStops: remainingHalts,
      currentStop,
    })
  }

  return (
    <>
      <Header active={active} />

      <main className="passenger-dashboard">
        <section
          id="overview"
          className="passenger-overview"
        >
          <div className="dashboard-title">
            <div>
              <span className="section-kicker">
                Passenger overview
              </span>

              <h1>
                Your journey, made clearer.
              </h1>
            </div>

            <span className="data-badge">
              {loading
                ? 'Loading train data'
                : error
                ? 'Backend error'
                : 'Backend connected'}
            </span>
          </div>

          {loading && (
            <EmptyState
              title="Loading train data"
              detail="Fetching your train information from RailETA."
            />
          )}

          {error && !loading && (
            <EmptyState
              title="Unable to load train"
              detail={error}
            />
          )}

          {!loading && !error && train && (
            <>
              <div className="passenger-overview-grid">
                <RailwayMap
                  trainNumber={trainNumber}
                  onLiveUpdate={handleLiveUpdate}
                />

                <StationEtaPanel
                  train={train}
                />
              </div>              <section className="feature-panel passenger-train-details">
                <div className="section-kicker">
                  Your train
                </div>

                <h2>{train.train_name}</h2>

                <div className="eta-list">
                  <div className="eta-row">
                    <span>Train number</span>

                    <b>
                      {train.train_number}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Train type</span>

                    <b>{train.train_type || '—'}</b>
                  </div>

                  <div className="eta-row">
                    <span>From</span>

                    <b>
                      {train.source_station_code ||
                        '—'}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>To</span>

                    <b>
                      {train.destination_station_code ||
                        '—'}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Distance</span>

                    <b>
                      {train.distance_km
                        ? `${train.distance_km} km`
                        : '—'}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Scheduled stops</span>

                    <b>{stops.length}</b>
                  </div>
                </div>
              </section>

              {liveInfo && (
                <section className="feature-panel passenger-train-details">
                  <div className="section-kicker">
                    Live status
                  </div>

                  <h2>
                    {liveInfo.delayMinutes > 0 ? (
                      <span style={{color:'#dc5032'}}>
                        Delayed {liveInfo.delayMinutes} min
                      </span>
                    ) : liveInfo.status === 'running'
                    ? 'Running on time'
                    : liveInfo.status || 'Tracking'}
                  </h2>

                  <div className="eta-list">
                    <div className="eta-row">
                      <span>Current station</span>

                      <b>
                        {liveInfo.currentStation && liveInfo.currentStationName
                          ? `${liveInfo.currentStation} — ${liveInfo.currentStationName}`
                          : liveInfo.currentStationName || liveInfo.currentStation || '—'}
                      </b>
                    </div>

                    <div className="eta-row">
                      <span>Next station</span>

                      <b>
                        {liveInfo.nextStation && liveInfo.nextStationName
                          ? `${liveInfo.nextStation} — ${liveInfo.nextStationName}`
                          : liveInfo.nextStationName || liveInfo.nextStation || '—'}
                      </b>
                    </div>

                    <div className="eta-row">
                      <span>Route progress</span>

                      <b>
                        {liveInfo.completedStops}{' '}
                        of{' '}
                        {liveInfo.totalStops}{' '}
                        scheduled halts
                      </b>
                    </div>

                    {liveInfo.totalRouteStations != null && liveInfo.totalRouteStations !== liveInfo.totalStops && (
                      <div className="eta-row">
                        <span>Total route stations</span>

                        <b>
                          {liveInfo.totalRouteStations}
                        </b>
                      </div>
                    )}

                    <div className="eta-row">
                      <span>Stops remaining</span>

                      <b>
                        {liveInfo.remainingStops}
                      </b>
                    </div>

                    {liveInfo.speedKmh != null && (
                      <div className="eta-row">
                        <span>Speed</span>

                        <b>
                          {liveInfo.speedKmh} km/h
                        </b>
                      </div>
                    )}
                  </div>
                </section>
              )}

              {stops.length > 0 && (
                <section className="feature-panel passenger-train-details">
                  <div className="section-kicker">
                    Scheduled route
                  </div>

                  <h2>
                    {stops.length} scheduled halts
                  </h2>

                  <div
                    className="eta-list"
                    style={{maxHeight:'600px', overflowY:'auto', paddingRight:'14px'}}
                  >
                    {stops
                      .map((stop) => {
                        const isNextStation =
                          liveInfo?.nextStation ===
                            stop.station_code

                        return (
                          <ScheduleStopRow
                            key={`${stop.station_code}-${stop.sequence}`}
                            stop={stop}
                            isNextStation={isNextStation}
                          />
                        )
                      })}
                  </div>
                </section>
              )}
            </>
          )}
        </section>

        <div className="feature-cards">
          <FeatureCard
            title="Stable Passenger ETA"
            description="See meaningful ETA changes without constant minute-by-minute fluctuations."
            label="View Stable ETA"
            href="#stable-eta"
          />

          <FeatureCard
            title="Simple Delay Explanation"
            description="Understand why your train is delayed and whether it is expected to recover."
            label="View Delay Explanation"
            href="#delay-explanation"
          />

          <FeatureCard
            title="Connection Risk"
            description="See whether your predicted arrival may affect a connecting train."
            label="Check Connection Risk"
            href="#connection-risk"
          />
        </div>

        <FeatureSections />

        <Link
          className="back-link dashboard-back"
          to="/"
        >
          ← Back to Home
        </Link>
      </main>
    </>
  )
}

/* =========================================================
   HOME
   ========================================================= */

function Home() {
  const [query, setQuery] = useState('')
  const nav = useNavigate()
  return (
    <>
      <header className="home-header">
        <div className="home-brand-card">
          <Link className="brand" to="/">
            <span className="brand-mark">
              <img src="/logo.png" alt="RailETA" />
            </span>
            <span>RailETA</span>
          </Link>
        </div>
        <div className="home-authority-card">
          <Link
            className="authority-link"
            to="/authority-login"
          >
            Authority Login
          </Link>
        </div>
      </header>

      <main className="home">
        <div className="home-copy">
          <h1>
            Beyond live status.
            <br />
            <em>See what happens next.</em>
          </h1>

          <p>
            Dynamic ETAs for every stop ahead.
          </p>

          <form
            className="search-bar"
            onSubmit={(e) => {
              e.preventDefault()

              if (!query.trim()) {
                return
              }

              nav(
                `/passenger-dashboard?train=${encodeURIComponent(
                  query.trim()
                )}`
              )
            }}
          >
            <input
              aria-label="Train number or train name"
              value={query}
              onChange={(e) =>
                setQuery(e.target.value)
              }
              placeholder="Enter train number or train name"
            />

            <button type="submit">
              Search train →
            </button>
          </form>
        </div>
      </main>
    </>
  )
}

/* =========================================================
   AUTHORITY LOGIN
   ========================================================= */

function Login() {
  const nav = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] =
    useState('')

  const [error, setError] = useState('')

  function handleLogin(e) {
    e.preventDefault()

    if (
      email.trim().toLowerCase() ===
        DEMO_EMAIL &&
      password === DEMO_PASSWORD
    ) {
      setError('')
      nav('/authority-search')
      return
    }

    setError(
      'Invalid demo credentials. Please use the credentials shown below.'
    )
  }

  return (
    <>
      <header className="home-header">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <img src="/logo.png" alt="RailETA" />
          </span>

          <span>RailETA</span>
        </Link>
      </header>

      <main className="login-page">
        <form onSubmit={handleLogin}>
          <span className="section-kicker">
            Authority access
          </span>

          <h1>Welcome back.</h1>

          <p className="login-demo-label">
            Demo Authority Access
          </p>

          <div className="login-demo-box">
            <span>
              Email:{' '}
              <strong>{DEMO_EMAIL}</strong>
            </span>

            <br />

            <span>
              Password:{' '}
              <strong>{DEMO_PASSWORD}</strong>
            </span>
          </div>

          <label>
            Work email

            <input
              type="email"
              required
              value={email}
              onChange={(e) => {
                setEmail(e.target.value)
                setError('')
              }}
              placeholder="Enter your work email"
            />
          </label>

          <label>
            Password

            <input
              type="password"
              required
              value={password}
              onChange={(e) => {
                setPassword(e.target.value)
                setError('')
              }}
              placeholder="Enter your password"
            />
          </label>

          {error && (
            <p className="login-error">
              {error}
            </p>
          )}

          <button type="submit">
            Continue →
          </button>

          <Link
            className="back-link"
            to="/"
          >
            ← Back to home
          </Link>
        </form>
      </main>
    </>
  )
}

/* =========================================================
   AUTHORITY SEARCH
   ========================================================= */

function AuthoritySearch() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] =
    useState(false)

  const [error, setError] = useState('')

  const nav = useNavigate()

  async function searchTrain(e) {
    e.preventDefault()

    const search = query.trim()

    if (!search) {
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await fetch(
        `${API_BASE}/trains`
      )

      if (!response.ok) {
        throw new Error(
          'Failed to fetch trains'
        )
      }

      const data = await response.json()

      const trains = data.trains || []

      const normalizedSearch =
        search.toLowerCase()

      const matches = trains.filter(
        (train) => {
          const number = String(
            train.train_number || ''
          ).toLowerCase()

          const name = String(
            train.train_name || ''
          ).toLowerCase()

          return (
            number === normalizedSearch ||
            name.includes(normalizedSearch)
          )
        }
      )

      if (matches.length > 0) {
        nav(
          `/authority-dashboard?train=${encodeURIComponent(
            matches[0].train_number
          )}`
        )
        return
      }

      /*
       * 2) Not in SQLite — try live API
       *    directly with the search term
       *    as a train number.
       */
      if (/^\d{5}$/.test(search)) {
        const liveRes = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(
            search
          )}/live`
        )

        if (liveRes.ok) {
          nav(
            `/authority-dashboard?train=${encodeURIComponent(
              search
            )}`
          )
          return
        }
      }

      setError(
        `No train found for "${search}".`
      )
    } catch (err) {
      console.error(err)

      setError(
        'Could not connect to the RailETA backend. Make sure FastAPI is running.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <header className="home-header">
        <div className="home-brand-card">
          <Link className="brand" to="/">
            <span className="brand-mark">
              <img src="/logo.png" alt="RailETA" />
            </span>

            <span>RailETA</span>
          </Link>
        </div>

        <div className="home-authority-card">
          <Link
            className="authority-link"
            to="/authority-login"
          >
            Sign out
          </Link>
        </div>
      </header>

      <main className="authority-search-page">
        <div className="authority-search-copy">
          <h1>Search for a train.</h1>

          <p>
            Enter a train number or name to open the
            authority workspace.
          </p>

          <form
            className="authority-search-form"
            onSubmit={searchTrain}
          >
            <input
              aria-label="Train number or train name"
              value={query}
              onChange={(e) =>
                setQuery(e.target.value)
              }
              placeholder="Enter train number or train name"
            />

            <button
              type="submit"
              disabled={loading}
            >
              {loading
                ? 'Searching...'
                : 'Search train →'}
            </button>
          </form>

          {error && (
            <p className="search-error">
              {error}
            </p>
          )}
        </div>
      </main>
    </>
  )
}

/* =========================================================
   AUTHORITY DASHBOARD
   ========================================================= */

function AuthorityDashboard() {
  const [query, setQuery] = useState('')
  const [train, setTrain] = useState(null)
  const [stops, setStops] = useState([])
  const [liveInfo, setLiveInfo] = useState(null)

  const [loading, setLoading] =
    useState(true)

  const [error, setError] = useState('')

  function handleLiveUpdate(data) {
    if (!data) return

    const route =
      Array.isArray(data.route)
        ? data.route
        : []

    const halts =
      route.filter((s) => s.isHalt)

    const completedHalts =
      halts.filter(
        (s) =>
          s.status === 'departed' ||
          s.status === 'passed'
      ).length

    const remainingHalts =
      halts.filter(
        (s) =>
          s.status === 'upcoming' ||
          s.status === 'approaching' ||
          s.status === 'arriving'
      ).length

    const currentStop =
      route.find(
        (s) =>
          s.stationCode ===
            data.currentLocation?.stationCode
      )

    const nextUpcomingHalt =
      halts.find(
        (s) =>
          s.status === 'upcoming' ||
          s.status === 'approaching' ||
          s.status === 'arriving'
      )

    setLiveInfo({
      status: data.status,
      delayMinutes:
        data.delayMinutes || 0,
      currentStation:
        data.currentLocation?.stationCode ||
        null,
      currentStationName:
        currentStop?.stationName ||
        data.currentLocation?.stationCode ||
        null,
      currentSequence:
        data.currentLocation?.sequence,
      segmentProgress:
        data.currentLocation?.segmentProgress,
      speedKmh:
        data.currentLocation?.speedKmh,
      nextStation:
        data.nextHalt?.stationCode ||
        nextUpcomingHalt?.stationCode || null,
      nextStationName:
        data.nextHalt?.stationName ||
        nextUpcomingHalt?.stationName || null,
      totalRouteStations: route.length,
      totalStops: halts.length,
      completedStops: completedHalts,
      remainingStops: remainingHalts,
      currentStop,
    })
  }

  const nav = useNavigate()
  const location = useLocation()

  const params = new URLSearchParams(
    location.search
  )

  const trainNumber = params.get('train')

  useEffect(() => {
    if (!trainNumber) {
      setLoading(false)
      setError('No train number was provided.')
      return
    }

    async function loadTrain() {
      setLoading(true)
      setError('')

      try {
        /*
         * First try the RailETA SQLite database.
         */

        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(
            trainNumber
          )}`
        )

        if (response.ok) {
          const data = await response.json()

          setTrain(data.train)
          setStops(data.stops || [])

          return
        }

        /*
         * If the train is not in SQLite,
         * try RailRadar directly.
         */

        if (response.status === 404) {
          const liveResponse = await fetch(
            `${API_BASE}/trains/${encodeURIComponent(
              trainNumber
            )}/live`
          )

          if (!liveResponse.ok) {
            if (liveResponse.status === 404) {
              throw new Error(
                `Train ${trainNumber} was not found in the RailETA timetable or RailRadar live data.`
              )
            }

            throw new Error(
              `Live train request failed (${liveResponse.status})`
            )
          }

          const liveResult =
            await liveResponse.json()

          const liveData =
            liveResult.data ?? liveResult

          const t = liveData.train || {}

          const liveTrain = {
            train_number:
              t.number ||
              liveData.trainNumber ||
              trainNumber,

            train_name:
              t.name ||
              liveData.trainName ||
              `Train ${trainNumber}`,

            train_type:
              t.type ||
              liveData.trainType ||
              'Live tracking',

            source_station_code:
              t.source?.code ||
              '—',

            destination_station_code:
              t.destination?.code ||
              '—',

            distance_km:
              t.distance ||
              null,

            runs_days:
              Array.isArray(t.runDays)
                ? t.runDays.join(', ')
                : null,
          }

          const liveRoute =
            Array.isArray(liveData.route)
              ? liveData.route
              : []

          /*
           * Only include actual halts
           * (isHalt=true), not passing stations.
           */
          const liveStops =
            liveRoute
              .filter((s) => s.isHalt)
              .map((s, i) => ({
                station_code:
                  s.stationCode || '—',
                station_name:
                  s.stationName || '',
                sequence:
                  s.sequence || i + 1,
                arrival_time:
                  s.scheduledArrival || null,
                departure_time:
                  s.scheduledDeparture || null,
                actual_arrival:
                  s.actualArrival || null,
                actual_departure:
                  s.actualDeparture || null,
                delay_arrival:
                  s.delayArrival ?? null,
                delay_departure:
                  s.delayDeparture ?? null,
                status:
                  s.status || 'upcoming',
              }))

          setTrain(liveTrain)
          setStops(liveStops)
          setError('')

          return
        }

        throw new Error(
          'Failed to fetch train data.'
        )
      } catch (err) {
        console.error(err)

        setTrain(null)
        setStops([])

        setError(
          err.message ||
            'Could not connect to the RailETA backend.'
        )
      } finally {
        setLoading(false)
      }
    }

    loadTrain()
  }, [trainNumber])

  async function searchAnotherTrain(e) {
    e.preventDefault()

    const search = query.trim()

    if (!search) {
      return
    }

    setLoading(true)
    setError('')

    try {
      /*
       * 1) Try SQLite train list first
       */
      const response = await fetch(
        `${API_BASE}/trains`
      )

      const data =
        response.ok
          ? await response.json()
          : { trains: [] }

      const trains = data.trains || []
      const normalizedSearch =
        search.toLowerCase()

      const matches = trains.filter(
        (item) => {
          const number = String(
            item.train_number || ''
          ).toLowerCase()
          const name = String(
            item.train_name || ''
          ).toLowerCase()

          return (
            number === normalizedSearch ||
            name.includes(normalizedSearch)
          )
        }
      )

      if (matches.length > 0) {
        setQuery('')
        nav(
          `/authority-dashboard?train=${encodeURIComponent(
            matches[0].train_number
          )}`
        )
        return
      }

      /*
       * 2) Not in SQLite — try live API
       *    directly with the search term
       *    as a train number.
       */
      if (/^\d{5}$/.test(search)) {
        const liveRes = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(
            search
          )}/live`
        )

        if (liveRes.ok) {
          setQuery('')
          nav(
            `/authority-dashboard?train=${encodeURIComponent(
              search
            )}`
          )
          return
        }
      }

      setError(
        `No train found for "${search}".`
      )

      setLoading(false)
    } catch (err) {
      console.error(err)

      setError(
        'Could not connect to the RailETA backend. Make sure FastAPI is running.'
      )

      setLoading(false)
    }
  }

  if (!trainNumber) {
    return <AuthoritySearch />
  }

  return (
    <>
      <Header authority />

      <main className="dashboard">
        <div className="dashboard-title">
          <div>
            <span className="section-kicker">
              Railway authority
            </span>

            <h1>
              Operational prediction workspace
            </h1>
          </div>

          <span className="data-badge">
            {loading
              ? 'Loading backend data'
              : error
              ? 'Backend error'
              : 'Backend connected'}
          </span>
        </div>

        <form
          className="authority-search-bar"
          onSubmit={searchAnotherTrain}
        >
          <input
            aria-label="Search another train"
            value={query}
            onChange={(e) =>
              setQuery(e.target.value)
            }
            placeholder="Search for another train"
          />

          <button type="submit">
            Search train →
          </button>
        </form>

        {loading && (
          <EmptyState
            title="Loading train data"
            detail="Fetching train information from the RailETA backend."
          />
        )}

        {error && !loading && (
          <EmptyState
            title="Unable to load train"
            detail={error}
          />
        )}

        {!loading && !error && train && (
          <>
            <div className="dashboard-grid">
              <RailwayMap
                trainNumber={trainNumber}
                onLiveUpdate={handleLiveUpdate}
              />

              <StationEtaPanel
                train={train}
              />
            </div>

            {liveInfo && (
              <section className="feature-panel authority-train-details">
                <div className="section-kicker">
                  Live status
                </div>

                <h2>
                  {liveInfo.delayMinutes > 0 ? (
                    <span style={{color:'#dc5032'}}>
                      Delayed {liveInfo.delayMinutes} min
                    </span>
                  ) : liveInfo.status === 'running'
                  ? 'Running on time'
                  : liveInfo.status || 'Tracking'}
                </h2>

                <div className="eta-list">
                  <div className="eta-row">
                    <span>Current station</span>

                    <b>
                      {liveInfo.currentStation && liveInfo.currentStationName
                        ? `${liveInfo.currentStation} — ${liveInfo.currentStationName}`
                        : liveInfo.currentStationName || liveInfo.currentStation || '—'}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Next station</span>

                    <b>
                      {liveInfo.nextStation && liveInfo.nextStationName
                        ? `${liveInfo.nextStation} — ${liveInfo.nextStationName}`
                        : liveInfo.nextStationName || liveInfo.nextStation || '—'}
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Route progress</span>

                    <b>
                      {liveInfo.completedStops}{' '}
                      of{' '}
                      {liveInfo.totalStops}{' '}
                      scheduled halts
                    </b>
                  </div>

                  <div className="eta-row">
                    <span>Stops remaining</span>

                    <b>
                      {liveInfo.remainingStops}
                    </b>
                  </div>

                  {liveInfo.speedKmh != null && (
                    <div className="eta-row">
                      <span>Speed</span>

                      <b>
                        {liveInfo.speedKmh} km/h
                      </b>
                    </div>
                  )}
                </div>
              </section>
            )}

            <section className="feature-panel authority-train-details">
              <div className="section-kicker">
                Timetable
              </div>

              <h2>
                {stops.length} scheduled halts
              </h2>

              {stops.length > 0 ? (
                <div
                  className="eta-list"
                  style={{maxHeight:'600px', overflowY:'auto', paddingRight:'14px'}}
                >
                  {stops
                    .map((stop) => {
                      const isNextStation =
                        liveInfo?.nextStation ===
                          stop.station_code

                      return (
                        <ScheduleStopRow
                          key={`${stop.station_code}-${stop.sequence}`}
                          stop={stop}
                          isNextStation={isNextStation}
                        />
                      )
                    })}
                </div>
              ) : (
                <EmptyState
                  title="No stop data"
                  detail="No scheduled stops were returned for this train."
                />
              )}
            </section>
          </>
        )}
      </main>
    </>
  )
}

/* =========================================================
   AUTHORITY FEATURE PAGES
   ========================================================= */

function AuthorityPage({ type }) {
  const configs = {
    propagation: [
      'Network-Aware Delay Propagation',
      'Prediction workspace for network delay movement.',
    ],

    recovery: [
      'Explainable Delay & Recovery Forecast',
      'Prediction workspace for delay source and recovery.',
    ],

    stable: [
      'Confidence-Aware Stable ETA',
      'Prediction workspace for stable passenger ETA.',
    ],
  }

  const config = configs[type]

  return (
    <>
      <Header authority />

      <main className="feature-page">
        <Link
          className="back-link"
          to="/authority-dashboard"
        >
          ← Back to Authority Dashboard
        </Link>

        <span className="section-kicker">
          Authority prediction
        </span>

        <h1>{config[0]}</h1>

        <p className="feature-lede">
          {config[1]}
        </p>

        <EmptyState
          title="No prediction data available"
          detail="Prediction models will populate this workspace once the ML layer is connected."
        />
      </main>
    </>
  )
}

/* =========================================================
   APP ROUTES
   ========================================================= */

export default function RailwayApp() {
  return (
    <HashRouter>
      <Routes>
        <Route
          path="/"
          element={<Home />}
        />

        <Route
          path="/authority-login"
          element={<Login />}
        />

        <Route
          path="/authority-search"
          element={<AuthoritySearch />}
        />

        <Route
          path="/passenger-dashboard"
          element={<PassengerDashboard />}
        />

        <Route
          path="/authority-dashboard"
          element={<AuthorityDashboard />}
        />

        <Route
          path="/authority-dashboard/delay-propagation"
          element={
            <AuthorityPage
              type="propagation"
            />
          }
        />

        <Route
          path="/authority-dashboard/delay-recovery"
          element={
            <AuthorityPage
              type="recovery"
            />
          }
        />

        <Route
          path="/authority-dashboard/stable-eta"
          element={
            <AuthorityPage
              type="stable"
            />
          }
        />
      </Routes>
    </HashRouter>
  )
}