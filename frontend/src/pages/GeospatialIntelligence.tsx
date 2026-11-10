import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import type { GeoJSONSource, Map as MapLibreMap, MapLayerMouseEvent } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { Feature, FeatureCollection, LineString, Point } from 'geojson'
import type { GeoCoordinate, GeoEvent, GeoEventPage, GeoRoute, GeoRoutePage, IncidentDetail, IncidentList } from '../api'
import { useApiResource } from '../useApiResource'
import { ApiState, DataBanner } from '../components/DataStates'
import { displayLabel, formatOpsDate, formatOpsMoney } from '../format'

// Bundle the worker as a Vite asset so MapLibre doesn't request a dependency URL
// that Vite's optimized-module server leaves pending in the browser.
setWorkerUrl(workerUrl)

const DEFAULT_MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const configuredStyle = import.meta.env.VITE_MAP_STYLE_URL
const MAP_STYLE = configuredStyle?.trim().toLowerCase() === 'none'
  ? null
  : configuredStyle?.trim() || DEFAULT_MAP_STYLE
const INITIAL_TIME_ANCHOR = Date.now()
const EMPTY_GEO_EVENTS: GeoEvent[] = []
const EMPTY_GEO_ROUTES: GeoRoute[] = []

type Range = '24h' | '7d' | '30d' | 'all'
type GeoFeatureProperties = { eventId: string; eventType: string; riskBand: string; incidentId: string }
type RouteFeatureProperties = { routeId: string; riskBand: string; incidentId: string }
type GeoPointCollection = FeatureCollection<Point, GeoFeatureProperties>
type GeoLineCollection = FeatureCollection<LineString, RouteFeatureProperties>
type LayerVisibility = { login: boolean; origin: boolean; beneficiary: boolean; routes: boolean }

function eventPoints(events: GeoEvent[]): GeoPointCollection {
  return {
    type: 'FeatureCollection',
    features: events.flatMap(event => event.coordinate ? [{
      type: 'Feature' as const,
      id: event.id,
      geometry: { type: 'Point' as const, coordinates: [Number(event.coordinate.longitude), Number(event.coordinate.latitude)] as [number, number] },
      properties: { eventId: event.id, eventType: event.event_type, riskBand: event.incident_risk_band ?? '', incidentId: event.incident_id ?? '' },
    }] : []),
  }
}

function routeLines(routes: GeoRoute[]): GeoLineCollection {
  return {
    type: 'FeatureCollection',
    features: routes.map(route => ({
      type: 'Feature' as const,
      id: route.id,
      geometry: { type: 'LineString' as const, coordinates: [position(route.origin), position(route.destination)] },
      properties: { routeId: route.id, riskBand: route.incident_risk_band ?? '', incidentId: route.incident_id ?? '' },
    })),
  }
}

function position(point: GeoCoordinate): [number, number] {
  return [Number(point.longitude), Number(point.latitude)]
}

function setTacticalStyle(map: MapLibreMap) {
  for (const layer of map.getStyle().layers ?? []) {
    const layerWithSource = layer as typeof layer & { 'source-layer'?: string }
    const sourceLayer = layerWithSource['source-layer'] ?? ''
    try {
      if (layer.type === 'background') map.setPaintProperty(layer.id, 'background-color', '#10191d')
      else if (layer.type === 'symbol') {
        map.setPaintProperty(layer.id, 'text-color', '#c0cbcd')
        map.setPaintProperty(layer.id, 'text-halo-color', '#111b20')
      } else if (sourceLayer === 'water' && (layer.type === 'fill' || layer.type === 'line')) {
        map.setPaintProperty(layer.id, layer.type === 'fill' ? 'fill-color' : 'line-color', '#142833')
      } else if (sourceLayer === 'building' && layer.type === 'fill') {
        map.setPaintProperty(layer.id, 'fill-color', '#1b292e')
      } else if (sourceLayer === 'transportation' && layer.type === 'line') {
        map.setPaintProperty(layer.id, 'line-color', [
          'match', ['get', 'class'], 'motorway', '#4a5c61', 'primary', '#405157', '#303f44',
        ])
      } else if ((sourceLayer === 'landcover' || sourceLayer === 'landuse') && layer.type === 'fill') {
        map.setPaintProperty(layer.id, 'fill-color', '#15211f')
      }
    } catch { /* Keep the provider's original paint for an incompatible layer. */ }
  }
}

function mapCollections(events: GeoEvent[], routes: GeoRoute[]): { points: GeoPointCollection; lines: GeoLineCollection } {
  return { points: eventPoints(events), lines: routeLines(routes) }
}

function GeoMap({
  events, routes, selectedEventId, selectedRouteId, visibility, onSelectEvent, onSelectRoute,
  fitRequest, mapRetry, onMapError, onMapReady, onMapInstance,
}: {
  events: GeoEvent[]
  routes: GeoRoute[]
  selectedEventId: string | null
  selectedRouteId: string | null
  visibility: LayerVisibility
  onSelectEvent: (id: string) => void
  onSelectRoute: (id: string) => void
  fitRequest: number
  mapRetry: number
  onMapError: (message: string) => void
  onMapReady: () => void
  onMapInstance: (map: MapLibreMap | null) => void
}) {
  const elementRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const collectionsRef = useRef(mapCollections(events, routes))
  const eventsRef = useRef(events)
  const routesRef = useRef(routes)
  const selectedEventRef = useRef(selectedEventId)
  const selectedRouteRef = useRef(selectedRouteId)
  const handlersRef = useRef({ onSelectEvent, onSelectRoute })
  const [readyGeneration, setReadyGeneration] = useState(0)
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    collectionsRef.current = mapCollections(events, routes)
    eventsRef.current = events
    routesRef.current = routes
    selectedEventRef.current = selectedEventId
    selectedRouteRef.current = selectedRouteId
    handlersRef.current = { onSelectEvent, onSelectRoute }
  }, [events, routes, selectedEventId, selectedRouteId, onSelectEvent, onSelectRoute])

  useEffect(() => {
    if (!elementRef.current || !MAP_STYLE) return
    let cancelled = false
    let didLoad = false
    const map = new maplibregl.Map({
      container: elementRef.current,
      style: MAP_STYLE,
      center: [78.9629, 20.5937],
      zoom: 4,
      pitch: 0,
      maxPitch: 70,
      attributionControl: { compact: false },
    })
    mapRef.current = map
    onMapInstance(map)
    map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right')
    map.on('load', () => {
      if (cancelled) return
      didLoad = true
      setTacticalStyle(map)
      map.addSource('geo-activity', { type: 'geojson', data: collectionsRef.current.points, cluster: true, clusterMaxZoom: 8, clusterRadius: 42 })
      map.addLayer({
        id: 'geo-clusters', type: 'circle', source: 'geo-activity', filter: ['has', 'point_count'],
        paint: { 'circle-color': '#24576a', 'circle-radius': ['step', ['get', 'point_count'], 17, 10, 22, 50, 29], 'circle-stroke-color': '#6ec2d0', 'circle-stroke-width': 1.2, 'circle-opacity': 0.92 },
      })
      map.addLayer({
        id: 'geo-cluster-count', type: 'symbol', source: 'geo-activity', filter: ['has', 'point_count'],
        layout: { 'text-field': ['get', 'point_count_abbreviated'], 'text-size': 11 }, paint: { 'text-color': '#e1f0f2' },
      })
      const types: [string, string, string][] = [
        ['geo-login', 'LOGIN_LOCATION', '#60a8bd'],
        ['geo-origin', 'TRANSACTION_ORIGIN', '#3da6d3'],
        ['geo-beneficiary', 'BENEFICIARY_LOCATION', '#dc9a4e'],
      ]
      for (const [id, eventType, color] of types) {
        map.addLayer({
          id, type: 'circle', source: 'geo-activity', filter: ['all', ['!', ['has', 'point_count']], ['==', ['get', 'eventType'], eventType]],
          paint: {
            'circle-color': ['match', ['get', 'riskBand'], 'CRITICAL', '#df5f59', 'ELEVATED', '#e29548', color],
            'circle-radius': ['case', ['==', ['get', 'eventId'], selectedEventRef.current ?? ''], 10, 6],
            'circle-stroke-color': '#d8f2f3', 'circle-stroke-width': ['case', ['==', ['get', 'eventId'], selectedEventRef.current ?? ''], 2, 1],
            'circle-opacity': 0.94,
          },
        })
      }
      map.addSource('geo-routes', { type: 'geojson', data: collectionsRef.current.lines, lineMetrics: true })
      map.addLayer({
        id: 'geo-route-line', type: 'line', source: 'geo-routes',
        paint: {
          'line-color': ['match', ['get', 'riskBand'], 'CRITICAL', '#df5f59', 'ELEVATED', '#e29548', '#329ac2'],
          'line-width': ['case', ['==', ['get', 'routeId'], selectedRouteRef.current ?? ''], 4, 2],
          'line-opacity': ['case', ['==', ['get', 'incidentId'], ''], 0.78, 0.94],
        },
      })
      map.addSource('geo-route-pulses', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      map.addLayer({ id: 'geo-route-pulse', type: 'circle', source: 'geo-route-pulses', paint: { 'circle-radius': 4.2, 'circle-color': '#b3f4ff', 'circle-stroke-color': '#236d88', 'circle-stroke-width': 2 } })
      map.on('click', 'geo-clusters', event => {
        const feature = event.features?.[0]
        if (!feature) return
        const source = map.getSource('geo-activity') as GeoJSONSource
        const clusterId = Number(feature.properties?.cluster_id)
        source.getClusterExpansionZoom(clusterId)
          .then(zoom => map.easeTo({ center: (feature.geometry as Point).coordinates as [number, number], zoom }))
          .catch(() => undefined)
      })
      const eventClick = (event: MapLayerMouseEvent) => {
        const id = event.features?.[0]?.properties?.eventId
        if (typeof id === 'string') handlersRef.current.onSelectEvent(id)
      }
      for (const [id] of types) map.on('click', id, eventClick)
      map.on('click', 'geo-route-line', event => {
        const id = event.features?.[0]?.properties?.routeId
        if (typeof id === 'string') handlersRef.current.onSelectRoute(id)
      })
      for (const id of ['geo-clusters', ...types.map(row => row[0]), 'geo-route-line']) {
        map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer' })
        map.on('mouseleave', id, () => { map.getCanvas().style.cursor = '' })
      }
      onMapReady()
      setReadyGeneration(value => value + 1)
    })
    map.on('error', event => {
      const message = event.error?.message ?? 'The map provider could not load its style or tiles.'
      onMapError(didLoad ? `Map tile request failed: ${message}` : `Map style could not be loaded: ${message}`)
    })
    return () => {
      cancelled = true
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      map.remove()
      if (mapRef.current === map) mapRef.current = null
      onMapInstance(null)
    }
  }, [mapRetry, onMapError, onMapReady, onMapInstance])

  useEffect(() => {
    const map = mapRef.current
    if (!map || readyGeneration === 0) return
    const pointSource = map.getSource('geo-activity') as GeoJSONSource | undefined
    const routeSource = map.getSource('geo-routes') as GeoJSONSource | undefined
    const pulseSource = map.getSource('geo-route-pulses') as GeoJSONSource | undefined
    pointSource?.setData(collectionsRef.current.points)
    routeSource?.setData(collectionsRef.current.lines)
    if (!pulseSource) return
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
    let cancelled = false
    let lastPulseUpdate = 0
    const animate = (now: number) => {
      if (cancelled) return
      if (now - lastPulseUpdate >= 50) {
        lastPulseUpdate = now
        const fraction = (now % 2600) / 2600
        const features: Feature<Point, { routeId: string }>[] = routesRef.current.slice(0, 100).map(route => {
          const from = position(route.origin)
          const to = position(route.destination)
          return {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [from[0] + (to[0] - from[0]) * fraction, from[1] + (to[1] - from[1]) * fraction] },
            properties: { routeId: route.id },
          }
        })
        pulseSource.setData({ type: 'FeatureCollection', features })
      }
      rafRef.current = requestAnimationFrame(animate)
    }
    rafRef.current = requestAnimationFrame(animate)
    return () => {
      cancelled = true
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
  }, [events, routes, readyGeneration])

  useEffect(() => {
    const map = mapRef.current
    if (!map || readyGeneration === 0) return
    for (const [layer, visible] of [
      ['geo-login', visibility.login], ['geo-origin', visibility.origin],
      ['geo-beneficiary', visibility.beneficiary], ['geo-route-line', visibility.routes], ['geo-route-pulse', visibility.routes],
    ] as const) {
      if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', visible ? 'visible' : 'none')
    }
    for (const layer of ['geo-login', 'geo-origin', 'geo-beneficiary']) {
      if (map.getLayer(layer)) {
        map.setPaintProperty(layer, 'circle-radius', ['case', ['==', ['get', 'eventId'], selectedEventRef.current ?? ''], 10, 6])
        map.setPaintProperty(layer, 'circle-stroke-width', ['case', ['==', ['get', 'eventId'], selectedEventRef.current ?? ''], 2, 1])
      }
    }
    if (map.getLayer('geo-route-line')) map.setPaintProperty('geo-route-line', 'line-width', ['case', ['==', ['get', 'routeId'], selectedRouteRef.current ?? ''], 4, 2])
  }, [visibility, selectedEventId, selectedRouteId, readyGeneration])

  useEffect(() => {
    const map = mapRef.current
    if (!map || readyGeneration === 0 || fitRequest === 0) return
    const bounds = new maplibregl.LngLatBounds()
    for (const event of eventsRef.current) if (event.coordinate) bounds.extend(position(event.coordinate))
    for (const route of routesRef.current) { bounds.extend(position(route.origin)); bounds.extend(position(route.destination)) }
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 55, maxZoom: 8, duration: 700 })
  }, [fitRequest, readyGeneration])

  return <div className="geo-map-canvas" ref={elementRef} aria-label="Synthetic geospatial activity map" />
}

export default function GeospatialIntelligence() {
  const [eventType, setEventType] = useState('')
  const [riskBand, setRiskBand] = useState('')
  const [incidentId, setIncidentId] = useState('')
  const [range, setRange] = useState<Range>('30d')
  const [timeAnchor, setTimeAnchor] = useState(INITIAL_TIME_ANCHOR)
  const [playhead, setPlayhead] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null)
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [visibility, setVisibility] = useState<LayerVisibility>({ login: true, origin: true, beneficiary: true, routes: true })
  const [fitRequest, setFitRequest] = useState(0)
  const [mapRetry, setMapRetry] = useState(0)
  const [mapError, setMapError] = useState<string | null>(null)
  const [mapReady, setMapReady] = useState(false)
  const mapInstanceRef = useRef<MapLibreMap | null>(null)

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: '500', offset: '0' })
    if (eventType) params.set('event_type', eventType)
    if (riskBand) params.set('risk_band', riskBand)
    if (incidentId) params.set('incident_id', incidentId)
    if (range !== 'all') {
      const ms = range === '24h' ? 86_400_000 : range === '7d' ? 604_800_000 : 2_592_000_000
      params.set('start_at', new Date(timeAnchor - ms).toISOString())
      params.set('end_at', new Date(timeAnchor).toISOString())
    }
    return params.toString()
  }, [eventType, incidentId, range, riskBand, timeAnchor])
  const eventData = useApiResource<GeoEventPage>(`/geospatial/events?${query}`)
  const routeQuery = useMemo(() => {
    const params = new URLSearchParams({ limit: '500', offset: '0' })
    if (riskBand) params.set('risk_band', riskBand)
    if (incidentId) params.set('incident_id', incidentId)
    if (range !== 'all') {
      const ms = range === '24h' ? 86_400_000 : range === '7d' ? 604_800_000 : 2_592_000_000
      params.set('start_at', new Date(timeAnchor - ms).toISOString())
      params.set('end_at', new Date(timeAnchor).toISOString())
    }
    return params.toString()
  }, [incidentId, range, riskBand, timeAnchor])
  const routeData = useApiResource<GeoRoutePage>(`/geospatial/routes?${routeQuery}`)
  const incidents = useApiResource<IncidentList>('/incidents?limit=100&offset=0')
  const availableRoutes = routeData.data?.items ?? EMPTY_GEO_ROUTES
  const routes = useMemo(() => eventType && eventType !== 'TRANSACTION_ROUTE' ? EMPTY_GEO_ROUTES : availableRoutes, [availableRoutes, eventType])
  const events = eventData.data?.items ?? EMPTY_GEO_EVENTS
  const selectedEvent = events.find(event => event.id === selectedEventId) ?? null
  const selectedRoute = routes.find(route => route.id === selectedRouteId) ?? null
  const activeIncidentId = incidentId || selectedEvent?.incident_id || selectedRoute?.incident_id || null
  const incident = useApiResource<IncidentDetail>(activeIncidentId ? `/incidents/${activeIncidentId}` : null)

  const allTimes = useMemo(() => [...events.map(event => new Date(event.event_at).getTime()), ...routes.map(route => new Date(route.event_at).getTime())].filter(Number.isFinite), [events, routes])
  const minTime = allTimes.length ? Math.min(...allTimes) : null
  const maxTime = allTimes.length ? Math.max(...allTimes) : null
  const currentTime = playhead ?? maxTime
  const visibleEvents = useMemo(() => events.filter(event => currentTime === null || new Date(event.event_at).getTime() <= currentTime), [events, currentTime])
  const visibleRoutes = useMemo(() => routes.filter(route => currentTime === null || new Date(route.event_at).getTime() <= currentTime), [routes, currentTime])

  const retryMap = useCallback(() => { setMapError(null); setMapReady(false); setMapRetry(value => value + 1) }, [])
  const handleMapError = useCallback((message: string) => setMapError(message), [])
  const handleMapReady = useCallback(() => { setMapError(null); setMapReady(true) }, [])
  const handleMapInstance = useCallback((map: MapLibreMap | null) => { mapInstanceRef.current = map }, [])
  const changeFilter = (setter: (value: string) => void, value: string) => { setter(value); setPlayhead(null); setPlaying(false); setSelectedEventId(null); setSelectedRouteId(null) }
  const resetView = () => mapInstanceRef.current?.easeTo({ center: [78.9629, 20.5937], zoom: 4, pitch: 0, bearing: 0, duration: 650 })
  const toggleLayer = (key: keyof LayerVisibility) => setVisibility(current => ({ ...current, [key]: !current[key] }))

  useEffect(() => {
    if (!playing || minTime === null || maxTime === null) return
    const timer = window.setInterval(() => {
      setPlayhead(current => {
        const next = (current ?? minTime) + Math.max(1000, (maxTime - minTime) / 120) * speed / 10
        if (next >= maxTime) { setPlaying(false); return maxTime }
        return next
      })
    }, 100)
    return () => window.clearInterval(timer)
  }, [playing, minTime, maxTime, speed])

  const selectedIncidentTransactions = useMemo(() => new Set(incident.data?.transactions.map(transaction => transaction.id) ?? []), [incident.data])
  const activeEventCount = visibleEvents.filter(event => event.coordinate !== null).length + visibleRoutes.length
  const noProvider = MAP_STYLE === null

  return <div className="ops-page geo-page">
    <DataBanner title="Synthetic geospatial activity · linked to persisted simulator transactions" tag="DEMO / SYNTHETIC DATA">
      City-centre demonstration coordinates are synthetic. A route connects explicit synthetic origin and beneficiary-location records; it does not represent a person’s physical journey or confirmed fraud.
    </DataBanner>

    <section className="panel ops-panel geo-toolbar-panel">
      <div className="geo-filters">
        <label>Event type<select value={eventType} onChange={event => changeFilter(setEventType, event.target.value)}><option value="">All types</option><option value="LOGIN_LOCATION">Login location</option><option value="TRANSACTION_ORIGIN">Transaction origin</option><option value="BENEFICIARY_LOCATION">Beneficiary location</option><option value="TRANSACTION_ROUTE">Transaction route</option></select></label>
        <label>Incident risk<select value={riskBand} onChange={event => changeFilter(setRiskBand, event.target.value)}><option value="">All evidence</option><option value="CRITICAL">Critical</option><option value="ELEVATED">Elevated</option><option value="GUARDED">Guarded</option><option value="LOW">Low</option></select></label>
        <label>Incident<select value={incidentId} onChange={event => changeFilter(setIncidentId, event.target.value)}><option value="">All incidents</option>{(incidents.data?.items ?? []).map(row => <option value={row.id} key={row.id}>{row.id.slice(0, 8).toUpperCase()} · {row.risk_band}</option>)}</select></label>
        <label>Time range<select value={range} onChange={event => { setRange(event.target.value as Range); setTimeAnchor(Date.now()); setPlayhead(null); setPlaying(false) }}><option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="all">All available</option></select></label>
      </div>
      <div className="geo-toolbar-actions"><span className="ops-muted">{eventData.data?.total ?? 0} location events · {routeData.data?.total ?? 0} routes · bounded to 500 each</span><button className="text-button" type="button" onClick={() => { setTimeAnchor(Date.now()); eventData.retry(); routeData.retry(); incidents.retry() }}>Refresh</button></div>
      {incidents.error && <div className="inline-api-error" role="alert">Incident filters unavailable: {incidents.error}</div>}
    </section>

    {(eventData.error || routeData.error || (eventData.loading && !eventData.data) || (routeData.loading && !routeData.data)) && <section className="panel ops-panel"><ApiState loading={eventData.loading || routeData.loading} error={eventData.error ?? routeData.error} retry={() => { eventData.retry(); routeData.retry() }} /></section>}

    <section className="geo-workspace">
      <div className="geo-map-panel panel">
      <div className="geo-map-heading"><div><span className="geo-kind">MAP VIEW · SYNTHETIC ACTIVITY</span><strong>{activeEventCount.toLocaleString()} visible features</strong></div><div className="geo-map-controls"><button type="button" onClick={() => mapInstanceRef.current?.zoomIn()}>＋ Zoom in</button><button type="button" onClick={() => mapInstanceRef.current?.zoomOut()}>− Zoom out</button><button type="button" onClick={resetView}>Reset view</button><button type="button" onClick={() => setFitRequest(value => value + 1)}>Fit to data</button></div></div>
        <div className="geo-layer-controls" aria-label="Map layer visibility">
          {([['login', 'Login locations'], ['origin', 'Transaction origins'], ['beneficiary', 'Beneficiary locations'], ['routes', 'Transaction routes']] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={visibility[key]} onChange={() => toggleLayer(key)} />{label}</label>)}
        </div>
        <div className="geo-map-shell">
          {noProvider ? <div className="geo-map-overlay"><strong>No map style configured</strong><span>Set VITE_MAP_STYLE_URL or remove the explicit “none” value. Geospatial records remain available in the event list.</span></div> : <GeoMap events={visibleEvents} routes={visibleRoutes} selectedEventId={selectedEventId} selectedRouteId={selectedRouteId} visibility={visibility} onSelectEvent={id => { setSelectedEventId(id); setSelectedRouteId(null) }} onSelectRoute={id => { setSelectedRouteId(id); setSelectedEventId(null) }} fitRequest={fitRequest} mapRetry={mapRetry} onMapError={handleMapError} onMapReady={handleMapReady} onMapInstance={handleMapInstance} />}
          {mapError && !noProvider && <div className="geo-map-overlay geo-map-error" role="alert"><strong>Basemap unavailable</strong><span>{mapError}</span><button type="button" onClick={retryMap}>Retry map</button><small>Map controls and the synthetic event list remain available while tiles are unavailable.</small></div>}
          {!mapError && !mapReady && !noProvider && <div className="geo-map-loading" role="status"><span className="loading-mark" />Loading geographic basemap…</div>}
          {!mapError && mapReady && activeEventCount === 0 && <div className="geo-map-no-data"><strong>No geospatial records match these filters</strong><span>Clear filters or generate synthetic events linked to existing completed simulator transactions.</span></div>}
        </div>
        <div className="geo-map-attribution-note">© OpenMapTiles · Data © OpenStreetMap contributors · Style/tiles: OpenFreeMap · DEMO/SYNTHETIC location records</div>
      </div>

      <aside className="panel geo-inspector">
        <div className="panel-heading"><div><h2>Activity inspection</h2><p>Select a marker or route to review persisted context</p></div></div>
        {selectedRoute ? <><span className="geo-detail-type">SYNTHETIC TRANSACTION ROUTE</span><h3>{selectedRoute.origin_label ?? 'Origin'} → {selectedRoute.destination_label ?? 'Beneficiary'}</h3><div className="geo-detail-grid"><div><span>Amount</span><strong>{formatOpsMoney(selectedRoute.amount, selectedRoute.currency)}</strong></div><div><span>Status</span><strong>{displayLabel(selectedRoute.transaction_status)}</strong></div><div><span>Timestamp</span><strong>{formatOpsDate(selectedRoute.event_at)}</strong></div><div><span>Risk evidence</span><strong>{selectedRoute.incident_risk_band ? `${displayLabel(selectedRoute.incident_risk_band)} · ${selectedRoute.incident_risk_score}/100` : 'No linked incident'}</strong></div></div><p className="geo-scenario-note">{displayLabel(selectedRoute.scenario ?? 'Synthetic scenario')}. This line represents a synthetic financial connection, not a person's physical travel path.</p><code>{selectedRoute.transaction_id}</code>{selectedRoute.incident_id && <p><button className="text-button" type="button" onClick={() => selectedRoute.incident_id && setIncidentId(selectedRoute.incident_id)}>Focus linked incident</button></p>}</>
          : selectedEvent ? <><span className="geo-detail-type">{displayLabel(selectedEvent.event_type)} · {selectedEvent.metadata.synthetic ? 'SYNTHETIC' : 'UNLABELLED'}</span><h3>{selectedEvent.metadata.city ?? selectedEvent.metadata.label ?? 'Location event'}</h3><div className="geo-detail-grid"><div><span>Timestamp</span><strong>{formatOpsDate(selectedEvent.event_at)}</strong></div><div><span>Risk context</span><strong>{selectedEvent.incident_risk_band ? `${displayLabel(selectedEvent.incident_risk_band)} · ${selectedEvent.incident_risk_score}/100` : 'No linked incident'}</strong></div><div><span>Account ID</span><strong className="geo-id">{selectedEvent.account_id ?? 'Not applicable'}</strong></div><div><span>Transaction ID</span><strong className="geo-id">{selectedEvent.transaction_id ?? 'Not linked'}</strong></div></div>{selectedEvent.metadata.scenario && <p className="geo-scenario-note">Scenario: {displayLabel(selectedEvent.metadata.scenario)}. Demonstration context only; this is not a confirmed fraud finding.</p>}{selectedEvent.incident_id && <p><button className="text-button" type="button" onClick={() => selectedEvent.incident_id && setIncidentId(selectedEvent.incident_id)}>Focus linked incident</button></p>}</>
          : <div className="ops-empty-inline">No marker or route selected. Event coordinates and account identifiers are displayed only for explicitly persisted synthetic geospatial records.</div>}
        {activeIncidentId && <div className="geo-incident-context"><div className="geo-incident-head"><span className="geo-detail-type">LINKED INCIDENT</span>{incidentId && <button type="button" className="text-button" onClick={() => { setIncidentId(''); setPlayhead(null) }}>Clear incident</button>}</div>{incident.error || (incident.loading && !incident.data) ? <ApiState loading={incident.loading} error={incident.error} retry={incident.retry} /> : incident.data && <><strong>{incident.data.title}</strong><p>{incident.data.risk_explanation}</p><div className="geo-detail-grid"><div><span>Risk</span><strong>{displayLabel(incident.data.risk_band)} · {incident.data.risk_score}/100</strong></div><div><span>Status</span><strong>{displayLabel(incident.data.status)}</strong></div><div><span>Linked transactions</span><strong>{selectedIncidentTransactions.size}</strong></div></div><div className="geo-incident-transactions">{incident.data.transactions.map(transaction => <span key={transaction.id}>{transaction.id.slice(0, 8).toUpperCase()} · {formatOpsMoney(transaction.amount, transaction.currency)} · {displayLabel(transaction.status)}</span>)}</div><details className="geo-incident-evidence"><summary>Associated rule outcomes · {incident.data.detections.length}</summary>{incident.data.detections.length ? incident.data.detections.map(detection => <article key={detection.id}><div><strong>{detection.rule_name}</strong><span>{displayLabel(detection.outcome)} · {displayLabel(detection.severity)}</span></div><p>{detection.explanation}</p></article>) : <p>No rule evaluations are associated with this incident.</p>}</details><code>{incident.data.id}</code></>}</div>}
        <div className="geo-legend"><span><i className="legend-login" />Login context</span><span><i className="legend-origin" />Transaction origin</span><span><i className="legend-beneficiary" />Beneficiary location</span><span><i className="legend-route" />Transaction connection</span><span><i className="legend-risk" />Incident-linked risk</span></div>
      </aside>
    </section>

    <section className="panel ops-panel geo-playback"><div className="panel-heading"><div><h2>Historical playback</h2><p>Client-side replay of the loaded event timestamps; playback does not create or modify records.</p></div><span className="data-scope-tag">DETERMINISTIC</span></div>
      <div className="geo-playback-controls"><button type="button" disabled={minTime === null} onClick={() => { if (playing) setPlaying(false); else { setPlayhead(minTime); setPlaying(true) } }}>{playing ? 'Pause' : 'Play'}</button><label>Speed<select value={speed} onChange={event => setSpeed(Number(event.target.value))}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label><input aria-label="Historical playback timestamp" type="range" min={minTime ?? 0} max={maxTime ?? 0} value={currentTime ?? 0} disabled={minTime === null || maxTime === null} onChange={event => { setPlaying(false); setPlayhead(Number(event.target.value)) }} /><time>{currentTime === null ? 'No event time' : formatOpsDate(new Date(currentTime).toISOString())}</time><button type="button" onClick={() => { setPlaying(false); setPlayhead(maxTime) }} disabled={maxTime === null}>Jump to latest</button></div>
    </section>

    <section className="panel ops-panel geo-event-table-panel"><div className="panel-heading"><div><h2>Matching geospatial events</h2><p>Page results are bounded; event records remain synthetic and are linked to simulator activity.</p></div><span className="section-count">{eventData.data?.total ?? 0} records</span></div>
      {eventData.loading && !eventData.data ? <ApiState loading error={null} /> : eventData.error ? <ApiState loading={false} error={eventData.error} retry={eventData.retry} /> : visibleEvents.length ? <div className="ops-table-wrap"><table className="ops-table geo-events-table"><thead><tr><th>TYPE</th><th>SIMULATED PLACE</th><th>UTC TIME</th><th>INCIDENT RISK</th><th>LINKED RECORD</th></tr></thead><tbody>{visibleEvents.map(event => <tr key={event.id} className={selectedEventId === event.id ? 'selected' : ''}><td><button className="ops-row-link" type="button" onClick={() => { setSelectedEventId(event.id); setSelectedRouteId(null) }}>{displayLabel(event.event_type)}</button></td><td>{event.metadata.city ?? 'Synthetic location'}<span className="ops-subline">DEMO/SYNTHETIC</span></td><td>{formatOpsDate(event.event_at)}</td><td>{event.incident_risk_band ? `${displayLabel(event.incident_risk_band)} · ${event.incident_risk_score}/100` : 'No incident link'}</td><td className="geo-id">{event.transaction_id ?? event.account_id ?? 'Unlinked'}</td></tr>)}</tbody></table></div> : <div className="ops-empty-inline">No geospatial events match the current selection. No coordinates are generated in response to these filters.</div>}
    </section>
  </div>
}
