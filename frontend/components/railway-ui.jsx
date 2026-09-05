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

const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  'http://127.0.0.1:8000/api/v1'
).replace(/\/+$/, '')

const ACCOUNT_ID = import.meta.env.VITE_ACCOUNT_ID || 'local-development-account'

const DEMO_EMAIL = 'authority@raileta.demo'
const DEMO_PASSWORD = 'RailETA@123'

function normalizeLiveStop(stop) {
  if (!stop || typeof stop !== 'object') return stop
  const coordinates = stop.coordinates
  const coordinateArray = Array.isArray(coordinates) ? coordinates : null
  return {
    ...stop,
    lat:
      stop.lat ??
      stop.latitude ??
      coordinates?.lat ??
      coordinates?.latitude ??
      coordinateArray?.[1],
    lng:
      stop.lng ??
      stop.longitude ??
      coordinates?.lng ??
      coordinates?.longitude ??
      coordinateArray?.[0],
  }
}

const passengerNav = [
  ['Overview', 'overview'],
  ['Stable ETA', 'stable-eta'],
  ['Delay Explanation', 'delay-explanation'],
  ['Connection Risk', 'connection-risk'],
  ['Developer API', 'developer-api'],
]

const authorityNav = [
  ['Overview', ''],
  ['Delay Propagation', 'delay-propagation'],
  ['Delay & Recovery', 'delay-recovery'],
  ['Stable ETA', 'stable-eta'],
  ['Developer API', 'developer-api'],
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

function etaStation(eta) {
  return eta?.next_station || eta?.stations?.[0] || null
}

function formatMinutes(value) {
  return value == null || !Number.isFinite(Number(value))
    ? '—'
    : `${Math.round(Number(value))} min`
}

function formatSignedMinutes(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const rounded = Math.round(Number(value))
  if (rounded === 0) return 'No change'
  return `${rounded > 0 ? '+' : ''}${rounded} min`
}

function recoverySummary(eta) {
  const station = etaStation(eta)
  const current = Number(eta?.current_delay_minutes)
  const predicted = Number(station?.predicted_delay_minutes)
  if (!Number.isFinite(current) || !Number.isFinite(predicted)) return '—'
  const change = Math.round(predicted - current)
  if (change === 0) return 'No predicted change'
  return change < 0
    ? `${Math.abs(change)} min recovery predicted`
    : `${change} min additional delay predicted`
}

function contributingFactors(eta) {
  const station = etaStation(eta)
  const current = Number(eta?.current_delay_minutes)
  const predicted = Number(station?.predicted_delay_minutes)
  if (!Number.isFinite(current) || !Number.isFinite(predicted)) return '—'
  const factors = []
  if (current > 0) factors.push('current carried RailRadar delay')
  if (predicted > current) factors.push('remaining section characteristics')
  if (predicted < current) factors.push('predicted recovery across remaining sections')
  if (station?.weather_context) factors.push('weather considered by the model')
  return factors.length > 0 ? factors.join(', ') : 'available live and scheduled route features'
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
  const location = useLocation()
  const query = authority ? location.search : ''

  const base = authority
    ? '/authority-dashboard'
    : '/passenger-dashboard'

  return (
    <header className="dashboard-header passenger-nav">
      <Link className="brand" to={`${base}${query}`}>
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
              to={`${base}${id ? `/${id}` : ''}${query}`}
              className={({ isActive }) =>
                isActive ? 'active' : ''
              }
            >
              {label}
            </NavLink>
          ) : id === 'developer-api' ? (
            <NavLink
              key={label}
              to={`${base}/developer-api`}
              className={({ isActive }) => (isActive ? 'active' : '')}
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
    const routeStops = (Array.isArray(
      liveData.route
    )
      ? liveData.route
      : liveData.route?.stops || []).map(normalizeLiveStop)

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

    const location = liveData.currentLocation || {}
    const normalizedLocation = normalizeLiveStop(location)
    let trainCoordinates = [
      Number(normalizedLocation.lng),
      Number(normalizedLocation.lat),
    ]
    if (!trainCoordinates.every(Number.isFinite)) {
      const currentIndex = validStops.findIndex(
        (stop) =>
          stop.stationCode === location.stationCode ||
          Number(stop.sequence) === Number(location.sequence)
      )
      const start = validStops[currentIndex >= 0 ? currentIndex : 0]
      const end = validStops[currentIndex >= 0 ? currentIndex + 1 : 1]
      const progress = Math.min(
        1,
        Math.max(0, Number(location.segmentProgress ?? 0))
      )
      if (start && end) {
        const startPoint = [Number(start.lng), Number(start.lat)]
        const endPoint = [Number(end.lng), Number(end.lat)]
        if ([...startPoint, ...endPoint].every(Number.isFinite)) {
          trainCoordinates = startPoint.map(
            (value, index) => value + (endPoint[index] - value) * progress
          )
        }
      }
    }
    if (trainCoordinates.every(Number.isFinite)) {
      const trainElement = document.createElement('div')
      trainElement.style.width = '18px'
      trainElement.style.height = '18px'
      trainElement.style.borderRadius = '50%'
      trainElement.style.background = '#dc5032'
      trainElement.style.border = '3px solid #fff'
      trainElement.style.boxShadow = '0 0 0 4px rgba(220,80,50,0.25), 0 2px 10px rgba(38,51,58,0.35)'
      markerRef.current = new Marker({ element: trainElement })
        .setLngLat(trainCoordinates)
        .setPopup(new Popup({ offset: 12 }).setText(`Train ${liveData.trainNumber || trainNumber}`))
        .addTo(map)
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

function FieldList({ fields, values = {} }) {
  return (
    <div className="eta-list">
      {fields.map((label) => (
        <div className="eta-row" key={label}>
          <span>{label}</span>
          <b>{values[label] ?? '—'}</b>
        </div>
      ))}
    </div>
  )
}

/* =========================================================
   STATION / TRAIN INFORMATION
   ========================================================= */

function StationEtaPanel({ train, eta }) {
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

      {etaStation(eta) && (
        <div className="eta-list">
          <div className="eta-row">
            <span>Upcoming station</span>
            <b>
              {etaStation(eta).station_name || etaStation(eta).station_code || '—'}
            </b>
          </div>
          <div className="eta-row">
            <span>Predicted arrival</span>
            <b>{formatIST(etaStation(eta).predicted_arrival)}</b>
          </div>
          <div className="eta-row">
            <span>Predicted delay</span>
            <b>
              {etaStation(eta).predicted_delay_minutes == null
                ? '—'
                : `${Math.round(etaStation(eta).predicted_delay_minutes)} min`}
            </b>
          </div>
          <div className="eta-row">
            <span>Reliability</span>
            <b>{etaStation(eta).confidence || '—'}</b>
          </div>
        </div>
      )}

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

function FeatureSections({
  eta,
  liveInfo,
  connectionRisk,
  connectingTrainNumber,
  onConnectingTrainNumberChange,
  onCheckConnection,
  connectionLoading,
  connectionError,
}) {
  const station = etaStation(eta)
  const stable = eta?.stable_eta || {}
  const predictedArrival = formatIST(station?.predicted_arrival)
  const currentDelay = formatMinutes(eta?.current_delay_minutes)
  const reliability = eta?.confidence || station?.confidence
  const currentStatus =
    eta?.current_position?.state || liveInfo?.status || '—'

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
            values={{
              'Current ETA': formatIST(stable.current_eta) === '—'
                ? predictedArrival
                : formatIST(stable.current_eta),
              'ETA Range': stable.eta_range
                ? `${formatIST(stable.eta_range.lower)} – ${formatIST(stable.eta_range.upper)}`
                : '—',
              'Previous ETA': formatIST(stable.previous_eta),
              Change: formatSignedMinutes(stable.change_minutes),
              Stability: stable.stability || '—',
              Reliability: stable.reliability || reliability,
            }}
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
            values={{
              'Current Delay': currentDelay,
              'Why is my train delayed?': contributingFactors(eta),
              'Expected Recovery': recoverySummary(eta),
              'Current Status': currentStatus,
            }}
          />

          <div className="plain-language">
            <strong>
              {eta ? 'Live prediction context' : 'Waiting for prediction'}
            </strong>

            <span>
              {eta
                ? `The current delay is ${currentDelay}; the returned station predictions are from the ${eta.prediction_source || 'available'} path. Weather is shown as context, not as proof of causation.`
                : 'Simple delay context will appear when backend data is available.'}
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
          <form
            className="authority-search-bar"
            onSubmit={onCheckConnection}
          >
            <input
              aria-label="Connecting train number"
              value={connectingTrainNumber}
              onChange={(event) => onConnectingTrainNumberChange(event.target.value)}
              placeholder="Optional: enter your connecting train number"
            />
            <button type="submit" disabled={connectionLoading}>
              {connectionLoading ? 'Checking...' : 'Check connection →'}
            </button>
          </form>

          <FieldList
            fields={[
              'Connecting Journey',
              'Predicted Arrival',
              'Connection Time',
              'Risk',
              'Recommendation',
            ]}
            values={{
              'Connecting Journey': connectionRisk?.connecting_train_name
                ? `${connectionRisk.connecting_train_number} — ${connectionRisk.connecting_train_name}`
                : connectionRisk?.status === 'unavailable'
                ? 'No connecting journey detected'
                : 'No connecting journey detected',
              'Predicted Arrival': formatIST(connectionRisk?.predicted_arrival),
              'Connection Time': formatMinutes(connectionRisk?.connection_time_minutes),
              Risk: connectionRisk?.risk || '—',
              Recommendation: connectionRisk?.recommendation || connectionRisk?.reason || 'No connecting journey detected',
            }}
          />

          {(connectionError || connectionRisk?.status === 'unavailable') && (
            <div className="plain-language">
              <strong>{connectionError ? 'Connection check unavailable' : 'Connection data unavailable'}</strong>
              <span>{connectionError || connectionRisk.reason}</span>
            </div>
          )}
        </div>
      </section>
    </>
  )
}

/* =========================================================
   SCHEDULE STOP ROW
   ========================================================= */

function ScheduleStopRow({ stop, isNextStation, prediction }) {
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

  const predictedDelay = Number(prediction?.predicted_delay_minutes)
  const hasPredictedArr =
    !actual_arrival && !!prediction?.predicted_arrival
  const depDelay =
    delay_departure ??
    delayMinutes(departure_time, actual_departure)
  const arrDelay =
    hasPredictedArr && Number.isFinite(predictedDelay)
      ? predictedDelay
      : delay_arrival ??
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
  } else if (hasPredictedArr) {
    displayArr = formatTimeIST(prediction.predicted_arrival)
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
            {!hasActualArr && !hasPredictedArr && (
              <span style={{color:'#526066'}}>
                {scheduledArr}
              </span>
            )}
            {(hasActualArr || hasPredictedArr) && (
              <>
                <span style={{
                  color:'#8a9399',
                  textDecoration: arrIsDelayed || arrIsEarly || hasPredictedArr ? 'line-through' : 'none',
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
                    : hasPredictedArr
                    ? '#4c7090'
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
            {!arrIsDelayed && !arrIsEarly && (hasActualArr || hasPredictedArr) && (
              <span style={{
                color: hasPredictedArr ? '#4c7090' : '#2d8a4e',
                fontSize:'11px',
                marginLeft:'4px',
              }}>
                {hasPredictedArr ? 'predicted' : '✓'}
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
  const [eta, setEta] = useState(null)
  const [etaError, setEtaError] = useState('')
  const [connectingTrainNumber, setConnectingTrainNumber] = useState('')
  const [connectionRisk, setConnectionRisk] = useState(null)
  const [connectionLoading, setConnectionLoading] = useState(false)
  const [connectionError, setConnectionError] = useState('')

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

  async function checkConnection(event) {
    event.preventDefault()
    const connecting = connectingTrainNumber.trim()
    const station = etaStation(eta)?.station_code
    if (!station) {
      setConnectionRisk(null)
      setConnectionError('The current ETA has no upcoming station for this connection check.')
      return
    }
    setConnectionLoading(true)
    setConnectionError('')
    try {
      const search = new URLSearchParams({
        current_train_number: trainNumber,
        connection_station: station,
      })
      if (connecting) search.set('connecting_train_number', connecting)
      const response = await fetch(`${API_BASE}/connections/risk?${search.toString()}`)
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body.detail || `Connection request failed (${response.status})`)
      }
      setConnectionRisk(body)
      if (body.status === 'unavailable') setConnectionError(body.reason || 'Connection data is unavailable.')
    } catch (err) {
      setConnectionRisk(null)
      setConnectionError(err.message || 'Could not load connection risk.')
    } finally {
      setConnectionLoading(false)
    }
  }

  useEffect(() => {
    if (!trainNumber) {
      setEta(null)
      setEtaError('')
      return
    }
    let cancelled = false
    async function loadEta() {
      try {
        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(trainNumber)}/eta`
        )
        if (!response.ok) {
          let detail = ''
          try {
            const body = await response.json()
            detail = body.detail || ''
          } catch {
            // Keep the status-based message when the backend has no JSON detail.
          }
          if (!cancelled) {
            setEta(null)
            setEtaError(detail || `ETA request failed (${response.status})`)
          }
          return
        }
        const result = await response.json()
        if (!cancelled) {
          setEta(result)
          setEtaError('')
        }
      } catch (err) {
        if (!cancelled) {
          setEta(null)
          setEtaError(err.message || 'Could not load live ETA.')
        }
      }
    }
    loadEta()
    const interval = setInterval(loadEta, 30000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
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
                : error || etaError
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
                  eta={eta}
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
                    Predicted downstream route
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
                        const prediction = eta?.stations?.find(
                          (item) => item.station_code === stop.station_code
                        )

                        return (
                          <ScheduleStopRow
                            key={`${stop.station_code}-${stop.sequence}`}
                            stop={stop}
                            isNextStation={isNextStation}
                            prediction={prediction}
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

        <FeatureSections
          eta={eta}
          liveInfo={liveInfo}
          connectionRisk={connectionRisk}
          connectingTrainNumber={connectingTrainNumber}
          onConnectingTrainNumberChange={setConnectingTrainNumber}
          onCheckConnection={checkConnection}
          connectionLoading={connectionLoading}
          connectionError={connectionError}
        />

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
  const [eta, setEta] = useState(null)
  const [etaError, setEtaError] = useState('')

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

  useEffect(() => {
    if (!trainNumber) {
      setEta(null)
      setEtaError('')
      return
    }
    let cancelled = false
    async function loadEta() {
      try {
        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(trainNumber)}/eta`
        )
        if (!response.ok) {
          let detail = ''
          try {
            const body = await response.json()
            detail = body.detail || ''
          } catch {
            // Keep the status-based message when the backend has no JSON detail.
          }
          if (!cancelled) {
            setEta(null)
            setEtaError(detail || `ETA request failed (${response.status})`)
          }
          return
        }
        const result = await response.json()
        if (!cancelled) {
          setEta(result)
          setEtaError('')
        }
      } catch (err) {
        if (!cancelled) {
          setEta(null)
          setEtaError(err.message || 'Could not load live ETA.')
        }
      }
    }
    loadEta()
    const interval = setInterval(loadEta, 30000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
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
              : error || etaError
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
                eta={eta}
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
                      const prediction = eta?.stations?.find(
                        (item) => item.station_code === stop.station_code
                      )

                      return (
                        <ScheduleStopRow
                          key={`${stop.station_code}-${stop.sequence}`}
                          stop={stop}
                          isNextStation={isNextStation}
                          prediction={prediction}
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
              'Downstream Delay Propagation',
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
  const location = useLocation()
  const trainNumber = new URLSearchParams(location.search).get('train')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(Boolean(trainNumber))
  const [error, setError] = useState('')

  const endpointByType = {
    propagation: 'delay-propagation',
    recovery: 'delay-recovery',
    stable: 'stable-eta',
  }

  useEffect(() => {
    if (!trainNumber) {
      setLoading(false)
      setData(null)
      setError('')
      return undefined
    }

    let cancelled = false
    async function loadFeature() {
      setLoading(true)
      setError('')
      try {
        const response = await fetch(
          `${API_BASE}/trains/${encodeURIComponent(trainNumber)}/${endpointByType[type]}`
        )
        const body = await response.json().catch(() => ({}))
        if (!response.ok) {
          throw new Error(body.detail || `Prediction request failed (${response.status})`)
        }
        if (!cancelled) setData(body)
      } catch (err) {
        if (!cancelled) {
          setData(null)
          setError(err.message || 'Could not load prediction data.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadFeature()
    return () => {
      cancelled = true
    }
  }, [trainNumber, type])

  function renderFeatureData() {
    if (type === 'stable') {
      return (
        <div className="feature-panel">
          <FieldList
            fields={['Current ETA', 'ETA Range', 'Previous ETA', 'Change', 'Stability', 'Reliability']}
            values={{
              'Current ETA': formatIST(data.current_eta),
              'ETA Range': data.eta_range
                ? `${formatIST(data.eta_range.lower)} – ${formatIST(data.eta_range.upper)}`
                : '—',
              'Previous ETA': formatIST(data.previous_eta),
              Change: formatSignedMinutes(data.change_minutes),
              Stability: data.stability || '—',
              Reliability: data.reliability || '—',
            }}
          />
          <div className="plain-language">
            <strong>Prediction history</strong>
            <span>{data.history_count_for_station || 0} stored snapshot(s) for this upcoming station. The ETA range uses the measured model test error and is not a probability guarantee.</span>
          </div>
        </div>
      )
    }

    if (type === 'recovery') {
      return (
        <div className="feature-panel">
          <FieldList
            fields={['Current Delay', 'Predicted Final Delay', 'Predicted Additional Delay', 'Expected Recovery', 'Current Status', 'Confidence']}
            values={{
              'Current Delay': formatMinutes(data.current_delay_minutes),
              'Predicted Final Delay': formatMinutes(data.predicted_final_delay_minutes),
              'Predicted Additional Delay': formatMinutes(data.predicted_additional_delay_minutes),
              'Expected Recovery': data.expected_recovery_minutes == null ? 'No recovery predicted' : formatMinutes(data.expected_recovery_minutes),
              'Current Status': data.current_status || '—',
              Confidence: data.confidence || data.data_quality || '—',
            }}
          />
          <div className="plain-language">
            <strong>Real-time explanation</strong>
            <span>{data.explanation || 'No explanation was returned.'}</span>
          </div>
        </div>
      )
    }

    return (
      <>
        <div className="feature-panel">
          <FieldList
            fields={['Current Delay', 'Upcoming Station', 'Maximum Predicted Delay', 'Affected Downstream Stations', 'Confidence']}
            values={{
              'Current Delay': formatMinutes(data.current_delay_minutes),
              'Upcoming Station': data.upcoming_station?.station_name || data.upcoming_station?.station_code || '—',
              'Maximum Predicted Delay': formatMinutes(data.downstream_impact?.maximum_predicted_delay_minutes),
              'Affected Downstream Stations': data.downstream_impact?.affected_downstream_station_count ?? '—',
              Confidence: data.confidence || data.data_quality || '—',
            }}
          />
          <div className="plain-language">
            <strong>Current train route only</strong>
            <span>{data.downstream_impact?.description || 'Downstream impact is unavailable.'}</span>
          </div>
        </div>
        <div className="feature-panel" style={{marginTop: '18px'}}>
          <div className="section-kicker">Returned downstream sections</div>
          <div className="eta-list">
            {(data.affected_downstream_stations || []).map((station) => (
              <div className="eta-row" key={`${station.station_code}-${station.scheduled_arrival}`}>
                <span>{station.station_name || station.station_code || 'Station'}</span>
                <b>
                  {formatMinutes(station.predicted_delay_minutes)}
                  {station.predicted_additional_delay_minutes != null
                    ? ` (${formatSignedMinutes(station.predicted_additional_delay_minutes)} section change)`
                    : ''}
                </b>
              </div>
            ))}
          </div>
          {(!data.affected_downstream_stations || data.affected_downstream_stations.length === 0) && (
            <EmptyState title="No downstream station predictions" detail="The live response did not include downstream sections." />
          )}
        </div>
      </>
    )
  }

  return (
    <>
      <Header authority />

      <main className="feature-page">
        <Link
          className="back-link"
          to={`/authority-dashboard${location.search}`}
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

        {!trainNumber && (
          <EmptyState
            title="No train selected"
            detail="Return to the authority dashboard and select a real train."
          />
        )}
        {loading && (
          <EmptyState
            title="Loading prediction data"
            detail={`Fetching the ${config[0].toLowerCase()} for train ${trainNumber}.`}
          />
        )}
        {error && !loading && (
          <EmptyState title="Prediction unavailable" detail={error} />
        )}
        {!loading && !error && data && renderFeatureData()}
      </main>
    </>
  )
}

/* =========================================================
   DEVELOPER API
   ========================================================= */

function developerApiError(body, fallback) {
  return body?.error?.message || body?.detail || fallback
}

async function developerApiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Account-ID': ACCOUNT_ID,
      ...(options.headers || {}),
    },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(developerApiError(body, `API request failed (${response.status})`))
  }
  return body
}

function DeveloperApiPage({ authority = false }) {
  const [keys, setKeys] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [showGenerate, setShowGenerate] = useState(false)
  const [keyName, setKeyName] = useState('')
  const [generatedKey, setGeneratedKey] = useState(null)
  const [copyLabel, setCopyLabel] = useState('Copy')
  const [revokeTarget, setRevokeTarget] = useState(null)
  const [actionLoading, setActionLoading] = useState(false)

  async function loadKeys() {
    setLoading(true)
    setError('')
    try {
      const body = await developerApiRequest('/api-keys')
      setKeys(Array.isArray(body.keys) ? body.keys : [])
    } catch (err) {
      setError(err.message || 'Could not load API keys.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadKeys()
  }, [])

  async function generateKey(event) {
    event.preventDefault()
    setActionLoading(true)
    setError('')
    setNotice('')
    try {
      const body = await developerApiRequest('/api-keys', {
        method: 'POST',
        body: JSON.stringify({ name: keyName.trim() }),
      })
      setGeneratedKey(body.key || null)
      setCopyLabel('Copy')
      setShowGenerate(false)
      setKeyName('')
      await loadKeys()
    } catch (err) {
      setError(err.message || 'Could not generate API key.')
    } finally {
      setActionLoading(false)
    }
  }

  async function revokeKey() {
    if (!revokeTarget) return
    setActionLoading(true)
    setError('')
    try {
      await developerApiRequest(`/api-keys/${encodeURIComponent(revokeTarget.id)}`, { method: 'DELETE' })
      setRevokeTarget(null)
      setNotice('API key revoked.')
      await loadKeys()
    } catch (err) {
      setError(err.message || 'Could not revoke API key.')
    } finally {
      setActionLoading(false)
    }
  }

  async function copyGeneratedKey() {
    if (!generatedKey) return
    try {
      await navigator.clipboard.writeText(generatedKey)
      setCopyLabel('Copied')
    } catch {
      setCopyLabel('Copy failed')
    }
  }

  const docsUrl = API_BASE.replace(/\/api\/v1\/?$/, '') + '/docs'
  const backPath = authority ? '/authority-dashboard' : '/passenger-dashboard'

  return (
    <>
      <Header authority={authority} active="developer-api" />
      <main className="feature-page developer-api-page">
        <Link className="back-link" to={backPath}>
          ← Back to {authority ? 'Authority Dashboard' : 'Passenger Dashboard'}
        </Link>

        <span className="section-kicker">Developer access</span>
        <h1>Developer API</h1>
        <p className="feature-lede">
          Connect your applications to RailETA's real-time train and ETA services.
        </p>

        <section className="feature-panel developer-api-panel">
          <div className="api-panel-heading">
            <div>
              <span className="section-kicker">Secure access</span>
              <h2>API Keys</h2>
              <p className="muted">Use an API key to authenticate requests to RailETA's API.</p>
            </div>
            <button type="button" onClick={() => { setShowGenerate(true); setError('') }}>
              + Generate API Key
            </button>
          </div>

          {notice && <div className="plain-language"><strong>{notice}</strong></div>}
          {error && <div className="plain-language"><strong>API key action unavailable</strong><span>{error}</span></div>}

          {loading ? (
            <div className="empty-state"><span>Loading API keys</span></div>
          ) : keys.length === 0 ? (
            <div className="empty-state api-empty-state">
              <strong>No API keys yet</strong>
              <span>Generate an API key to start integrating RailETA with your application.</span>
              <button type="button" onClick={() => { setShowGenerate(true); setError('') }}>Generate API Key</button>
            </div>
          ) : (
            <div className="api-key-list">
              {keys.map((item) => (
                <div className="api-key-row" key={item.id}>
                  <div>
                    <strong>{item.name}</strong>
                    <span className="api-key-mask">{item.masked_key}</span>
                  </div>
                  <div className="api-key-meta">
                    <span>Created {item.created_at ? new Date(item.created_at).toLocaleDateString() : '—'}</span>
                    <span>Last used {item.last_used_at ? new Date(item.last_used_at).toLocaleString() : 'Never'}</span>
                    <b>{item.status}</b>
                  </div>
                  {item.status === 'active' && (
                    <button type="button" onClick={() => setRevokeTarget(item)}>Revoke</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="feature-panel developer-api-panel">
          <span className="section-kicker">Integration</span>
          <h2>How to use the API</h2>
          <p className="muted">Include your API key when making requests to RailETA.</p>
          <div className="api-code-label">Example request</div>
          <pre className="api-code">{`GET /api/v1/trains/{train_number}/live\nX-API-Key: YOUR_API_KEY`}</pre>
        </section>

        <section className="developer-api-grid">
          <div className="feature-panel developer-api-panel">
            <span className="section-kicker">Reference</span>
            <h2>API Documentation</h2>
            <p className="muted">Explore RailETA's API endpoints, request parameters, responses, and authentication requirements.</p>
            <button type="button" onClick={() => window.open(docsUrl, '_blank', 'noopener,noreferrer')}>
              Open API Docs →
            </button>
          </div>
          <div className="feature-panel developer-api-panel">
            <span className="section-kicker">Access</span>
            <h2>API Access</h2>
            <p className="muted">Your API key provides authenticated access to RailETA services available to your account.</p>
            <p className="muted">API requests are subject to the configured rate limit.</p>
          </div>
        </section>
      </main>

      {showGenerate && (
        <div className="api-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setShowGenerate(false) }}>
          <div className="api-modal" role="dialog" aria-modal="true" aria-labelledby="generate-api-key-title">
            <span className="section-kicker">API Keys</span>
            <h2 id="generate-api-key-title">Generate API Key</h2>
            <form onSubmit={generateKey}>
              <label htmlFor="api-key-name">Key name</label>
              <input id="api-key-name" value={keyName} onChange={(event) => setKeyName(event.target.value)} placeholder="My Application" maxLength={80} autoFocus />
              <span className="muted">Give this key a name so you can identify it later.</span>
              <div className="api-modal-actions">
                <button type="button" onClick={() => setShowGenerate(false)}>Cancel</button>
                <button type="submit" disabled={actionLoading || !keyName.trim()}>{actionLoading ? 'Generating...' : 'Generate Key'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {generatedKey && (
        <div className="api-modal-backdrop" role="presentation">
          <div className="api-modal" role="dialog" aria-modal="true" aria-labelledby="generated-api-key-title">
            <span className="section-kicker">API Keys</span>
            <h2 id="generated-api-key-title">API key generated</h2>
            <div className="plain-language"><strong>Copy this key now.</strong><span>For security, you won't be able to view it again.</span></div>
            <code className="api-key-plaintext">{generatedKey}</code>
            <div className="api-modal-actions">
              <button type="button" onClick={copyGeneratedKey}>{copyLabel}</button>
              <button type="button" onClick={() => setGeneratedKey(null)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {revokeTarget && (
        <div className="api-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setRevokeTarget(null) }}>
          <div className="api-modal" role="dialog" aria-modal="true" aria-labelledby="revoke-api-key-title">
            <span className="section-kicker">API Keys</span>
            <h2 id="revoke-api-key-title">Revoke API key?</h2>
            <p className="muted">This will immediately prevent applications using this key from accessing RailETA.</p>
            <div className="api-modal-actions">
              <button type="button" onClick={() => setRevokeTarget(null)}>Cancel</button>
              <button type="button" onClick={revokeKey} disabled={actionLoading}>{actionLoading ? 'Revoking...' : 'Revoke Key'}</button>
            </div>
          </div>
        </div>
      )}
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

        <Route
          path="/passenger-dashboard/developer-api"
          element={<DeveloperApiPage />}
        />

        <Route
          path="/authority-dashboard/developer-api"
          element={<DeveloperApiPage authority />}
        />
      </Routes>
    </HashRouter>
  )
}
