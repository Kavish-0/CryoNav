/* ═══════════════════════════════════════════════════════════════
   Map Page — the operational workspace.

     planner + layers  |  map  |  routes, hazards, guidance + legend

   Everything drawn comes from the backend: sea ice (GET /observed,
   /forecast, /grid), iceberg drift ensembles (GET /bergs), the NIC feed
   (GET /bergs/live), currents and wind (GET /ocean, /weather — optional),
   bathymetry (GET /grid) and every route alternative (POST /route).
   Route indications — direction, legs, ice along the route, bergs near
   it — are derived in the browser from those responses and labelled so.

   Two projections: Web Mercator on keyless Esri tiles, and Antarctic Polar
   Stereographic (EPSG:3031) on NASA GIBS tiles (utils/antarcticCrs.js).
   MapContainer cannot change its `crs` after mount, so switching
   projection remounts it via `key`.

   Below NARROW_QUERY the two side panels fold into one tabbed panel so the
   map keeps most of the screen; below 860px the panel moves under the map.
   ═══════════════════════════════════════════════════════════════ */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import { MapContainer, TileLayer, Circle, Polyline, Tooltip } from 'react-leaflet';
import {
  Compass, Layers, Route as RouteIcon, Navigation, ShieldAlert, ListOrdered, Loader2,
} from 'lucide-react';
import useAppStore from '@stores/useAppStore';
import useMapStore from '@stores/useMapStore';
import useRouteStore from '@stores/useRouteStore';
import { useIcebergsMeta } from '@hooks/useIcebergs';
import { useGrid } from '@hooks/useGrid';
import { useObserved } from '@hooks/useObserved';
import { useForecast } from '@hooks/useForecast';
import { useLiveBergs } from '@hooks/useProvenance';
import { useOcean, useWeather } from '@hooks/useOcean';
import { useConfig } from '@hooks/useConfig';
import { usePlanRoutes } from '@hooks/useRouteCalculation';
import { useSelectedRoute } from '@hooks/useSelectedRoute';
import { useRouteHazards } from '@hooks/useRouteHazards';
import { useMediaQuery } from '@hooks/useMediaQuery';
import SicCanvasLayer, { sicColor, diffColor } from '@components/map/SicCanvasLayer';
import IcebergLayer from '@components/map/IcebergLayer';
import BathymetryLayer from '@components/map/BathymetryLayer';
import LiveIcebergLayer from '@components/map/LiveIcebergLayer';
import MapControls from '@components/map/MapControls';
import PlaceMarkers from '@components/map/PlaceMarkers';
import VectorFieldLayer from '@components/map/VectorFieldLayer';
import MapLegend from '@components/map/MapLegend';
import CoordinateChips from '@components/map/CoordinateChips';
import RouteLayer from '@components/map/RouteLayer';
import MapLayersPanel from '@components/map/MapLayersPanel';
import PanelSection from '@components/map/PanelSection';
import RoutePlanner from '@components/routes/RoutePlanner';
import RouteComparison from '@components/routes/RouteComparison';
import RouteMetrics from '@components/routes/RouteMetrics';
import RouteHazards from '@components/routes/RouteHazards';
import NavigationGuidance from '@components/routes/NavigationGuidance';
import RiskIndicator from '@components/routes/RiskIndicator';
import '@styles/map-layers.css';
import {
  MAP_DEFAULTS, RESEARCH_STATIONS, DEPARTURE_PORTS, BASEMAPS,
  POLAR_BASEMAPS, POLAR_OVERLAYS, GIBS_ATTRIBUTION,
  DOMAIN_BOUNDS, ANTARCTIC_CIRCLE_RADIUS_M,
  gibsTileUrl, clampGibsDate,
} from '@utils/constants';
import { EPSG3031, GIBS_TILE_SIZE, GIBS_MAX_ZOOM } from '@utils/antarcticCrs';
import { createGridLocator } from '@utils/navigation';
import { formatNauticalMiles, formatDuration } from '@utils/formatters';

/** Below this width the planner and results share one tabbed panel. */
const NARROW_QUERY = '(max-width: 1360px)';

const TABS = [
  { id: 'plan', label: 'Plan' },
  { id: 'routes', label: 'Routes' },
  { id: 'layers', label: 'Layers' },
];

/* Per-projection map view.

   Polar sits on the pole. Zoom is fractional (proj4leaflet interpolates
   between the GIBS resolutions). z0.25 frames the whole continent including
   the Antarctic Peninsula with only a sliver of grid edge showing. */
const VIEWS = {
  mercator: { center: MAP_DEFAULTS.center, zoom: MAP_DEFAULTS.zoom, minZoom: MAP_DEFAULTS.minZoom, zoomSnap: 1 },
  polar: { center: [-90, 0], zoom: 0.25, minZoom: 0, zoomSnap: 0.25 },
};

/** A GIBS raster, sized to whatever depth its TileMatrixSet actually has. */
function GibsLayer({ spec, date, ...rest }) {
  return (
    <TileLayer
      url={gibsTileUrl(spec, date)}
      attribution={GIBS_ATTRIBUTION}
      tileSize={GIBS_TILE_SIZE}
      minZoom={0}
      maxZoom={GIBS_MAX_ZOOM['250m']}
      maxNativeZoom={GIBS_MAX_ZOOM[spec.tms]}
      noWrap
      {...rest}
    />
  );
}

/** Floating summary of the selected route, so it stays visible whatever panel is open. */
function SelectedRouteChip({ route, hazards, isCalculating, onOpen }) {
  if (isCalculating) {
    return (
      <div className="map-route-chip is-busy" role="status">
        <Loader2 size={13} className="rp-spin" /> Calculating routes…
      </div>
    );
  }
  if (!route?.success) return null;

  const danger = hazards.proximity?.filter((p) => p.level === 'danger').length ?? 0;
  const caution = hazards.proximity?.filter((p) => p.level === 'caution').length ?? 0;
  let screen = null;
  if (danger > 0) screen = <RiskIndicator level="high" label={`${danger} berg${danger > 1 ? 's' : ''}: danger`} />;
  else if (caution > 0) screen = <RiskIndicator level="moderate" label={`${caution} berg${caution > 1 ? 's' : ''}: caution`} />;
  else if (hazards.proximity) screen = <RiskIndicator level="low" label="No bergs flagged" />;

  const content = (
    <>
      <span className="route-letter" style={{ '--route-color': route.color }}>{route.letter}</span>
      <span className="mrc-text">
        <strong>Route {route.letter} · {route.label}</strong>
        <span className="mrc-stats">
          {formatNauticalMiles(route.distanceNm)} · {route.timeH != null ? formatDuration(route.timeH) : '—'}
        </span>
      </span>
      {screen}
    </>
  );

  return onOpen ? (
    <button type="button" className="map-route-chip" style={{ '--route-color': route.color }} onClick={onOpen}>
      {content}
    </button>
  ) : (
    <div className="map-route-chip" style={{ '--route-color': route.color }}>{content}</div>
  );
}

export default function MapPage() {
  const selectedDate = useAppStore((s) => s.selectedDate);
  const layers = useMapStore((s) => s.layers);
  const toggleLayer = useMapStore((s) => s.toggleLayer);
  const bergHorizon = useMapStore((s) => s.bergHorizon);
  const setBergHorizon = useMapStore((s) => s.setBergHorizon);

  const origin = useRouteStore((s) => s.origin);
  const destination = useRouteStore((s) => s.destination);
  const setOrigin = useRouteStore((s) => s.setOrigin);
  const setDestination = useRouteStore((s) => s.setDestination);
  const isCalculating = useRouteStore((s) => s.isCalculating);
  const routeLastRequest = useRouteStore((s) => s.lastRequest);
  const { plan } = usePlanRoutes();
  const { result: routeResult, route: selectedRoute } = useSelectedRoute();
  const hazards = useRouteHazards(selectedRoute, routeResult);

  const narrow = useMediaQuery(NARROW_QUERY);
  const [tab, setTab] = useState('plan');
  const [showLiveBergs, setShowLiveBergs] = useState(false);

  /* ── Scrub state ── */
  const [leadDay, setLeadDay] = useState(7);
  const [sicMode, setSicMode] = useState('observed');
  const [playing, setPlaying] = useState(false);

  const bergsQuery = useIcebergsMeta(selectedDate, bergHorizon);
  const bergs = bergsQuery.data?.bergs;

  /* Grid geometry is fetched once and reused by every raster layer.
     Fields are only requested when something actually needs them, so
     toggling layers doesn't pull megabytes nobody is looking at. */
  const { data: grid } = useGrid();
  const sicOn = layers.seaIce || layers.seaIceForecast;

  const wantForecast = sicOn && (sicMode === 'forecast' || sicMode === 'difference');
  const forecast = useForecast(wantForecast ? selectedDate : null, leadDay);

  /* Observed is needed either on its own, or at the forecast's VALID date
     so the difference compares like with like rather than the field the
     forecast was initialised from. */
  const validDate = forecast.data?.stats?.valid_date;
  const observedDate = sicMode === 'difference' ? validDate : selectedDate;
  const observed = useObserved(sicOn && observedDate ? observedDate : null);

  /* forecast − observed, both at the valid date. Positive = the model has
     more ice than reality; negative = less. */
  const diffField = useMemo(() => {
    if (sicMode !== 'difference') return null;
    const f = forecast.data?.sic;
    const o = observed.data?.sic;
    if (!f || !o) return null;
    return f.map((row, y) => row.map((v, x) => v - (o[y]?.[x] ?? 0)));
  }, [sicMode, forecast.data, observed.data]);

  /* Real CMEMS currents and ERA5 wind, fetched only when their layer is on. */
  const ocean = useOcean(layers.oceanCurrents ? selectedDate : null, 6);
  const weather = useWeather(layers.weather ? selectedDate : null, 6);

  const liveBergs = useLiveBergs();
  const { data: config } = useConfig();

  /* Opens in Mercator on satellite imagery, matching the bundled web/
     client. Polar stereographic stays one click away. */
  const [projection, setProjection] = useState('mercator');
  const [basemapId, setBasemapId] = useState(MAP_DEFAULTS.basemap);
  const [polarBasemapId, setPolarBasemapId] = useState('blue_marble');
  const [polarOverlays, setPolarOverlays] = useState({ seaIce: true, coastlines: true, graticule: false });

  const isPolar = projection === 'polar';
  const basemap = BASEMAPS[basemapId] || BASEMAPS[MAP_DEFAULTS.basemap];
  const polarBasemap = POLAR_BASEMAPS[polarBasemapId] || POLAR_BASEMAPS.blue_marble;
  const view = VIEWS[projection];
  const seaIceDate = clampGibsDate(selectedDate, POLAR_OVERLAYS.seaIce.available);

  /* On a narrow screen, show the results as soon as a calculation lands. */
  useEffect(() => {
    if (narrow && routeResult) setTab('routes');
  }, [narrow, routeResult]);

  /* The lead-day animation lives in MapControls; stop it when that panel is hidden. */
  useEffect(() => {
    if (narrow && tab !== 'layers') setPlaying(false);
  }, [narrow, tab]);

  /* ── Cursor inspection: the grid cell under the pointer ── */
  const locator = useMemo(() => createGridLocator(grid), [grid]);
  const inspectField = !sicOn
    ? null
    : sicMode === 'difference' ? diffField : sicMode === 'forecast' ? forecast.data?.sic : observed.data?.sic;

  const inspect = useCallback((lat, lon) => {
    if (!locator || !grid) return null;
    const cell = locator.nearest(lat, lon);
    if (!cell) return null;
    if (grid.land_mask?.[cell.y]?.[cell.x] > 0.5) return 'Land / ice shelf';
    const parts = [];
    const v = inspectField?.[cell.y]?.[cell.x];
    if (Number.isFinite(v)) {
      parts.push(sicMode === 'difference'
        ? `ΔSIC ${v > 0 ? '+' : ''}${Math.round(v * 100)}%`
        : `${sicMode === 'forecast' ? 'Forecast' : 'Observed'} SIC ${Math.round(v * 100)}%`);
    }
    const depth = grid.bathy?.[cell.y]?.[cell.x];
    if (Number.isFinite(depth) && depth < 0) parts.push(`${Math.round(-depth).toLocaleString('en-US')} m deep`);
    return parts.join(' · ') || null;
  }, [locator, grid, inspectField, sicMode]);

  /* Route screen results, matched to the bergs on the map. Only meaningful
     when the map shows the route's own departure date. */
  const proximityById = useMemo(() => {
    if (!hazards.proximity || routeResult?.depart_date !== selectedDate) return null;
    return new Map(hazards.proximity.map((p) => [p.bergId, p]));
  }, [hazards.proximity, routeResult, selectedDate]);

  /* ── Endpoints picked on the map ── */
  const endpointFor = useCallback((place) => ({
    id: place.id,
    name: config?.origins?.[place.id]?.name || config?.stations?.[place.id]?.name || place.name,
    lat: place.lat,
    lon: place.lon,
  }), [config]);

  const pickOrigin = useCallback((place) => {
    const next = endpointFor(place);
    setOrigin(next);
    const other = useRouteStore.getState().destination;
    if (other && other.id !== next.id) plan({ origin: next });
  }, [endpointFor, setOrigin, plan]);

  const pickDestination = useCallback((place) => {
    const next = endpointFor(place);
    setDestination(next);
    const other = useRouteStore.getState().origin;
    if (other && other.id !== next.id) plan({ destination: next });
  }, [endpointFor, setDestination, plan]);

  const routeList = routeResult?.list || [];
  const successCount = routeList.filter((r) => r.success).length;

  const layerNotes = {
    oceanCurrents: layers.oceanCurrents && ocean.isError ? 'Unavailable: this backend does not serve GET /ocean.' : null,
    weather: layers.weather && weather.isError ? 'Unavailable: this backend does not serve GET /weather.' : null,
    icebergs: bergsQuery.data?.source === 'synthetic'
      ? 'Synthetic berg positions (demo data), not observations.'
      : bergsQuery.data?.source === 'observed' ? 'Observed BYU/NIC tracks, drifted by the ensemble model.' : null,
  };

  /* ── Panels ── */
  const plannerPanel = (
    <PanelSection title="Voyage planner" icon={Compass}>
      <RoutePlanner />
    </PanelSection>
  );

  const layersPanel = (
    <>
      <PanelSection title="Map & layers" icon={Layers} defaultOpen={!narrow ? false : true}>
        <MapLayersPanel
          projection={projection} onProjectionChange={setProjection}
          basemapId={basemapId} onBasemapChange={setBasemapId}
          polarBasemapId={polarBasemapId} onPolarBasemapChange={setPolarBasemapId}
          polarOverlays={polarOverlays}
          onTogglePolarOverlay={(id) => setPolarOverlays((p) => ({ ...p, [id]: !p[id] }))}
          seaIceDate={seaIceDate} selectedDate={selectedDate}
          layers={layers} onToggleLayer={toggleLayer} layerNotes={layerNotes}
          showLiveBergs={showLiveBergs} onToggleLiveBergs={() => setShowLiveBergs((v) => !v)}
          liveBergsError={liveBergs.isError}
        />
      </PanelSection>
      <MapControls
        leadDay={leadDay} setLeadDay={setLeadDay}
        bergHorizon={bergHorizon} setBergHorizon={setBergHorizon}
        sicMode={sicMode} setSicMode={setSicMode}
        playing={playing} setPlaying={setPlaying}
        validDate={validDate}
        forecastSource={forecast.data?.source}
      />
    </>
  );

  const routesPanel = routeList.length ? (
    <>
      <PanelSection title="Route alternatives" icon={RouteIcon} meta={`${successCount}/${routeList.length}`}>
        <RouteComparison result={routeResult} variant="cards" />
      </PanelSection>
      <PanelSection title="Selected route" icon={Navigation}>
        <RouteMetrics route={selectedRoute} result={routeResult} />
      </PanelSection>
      <PanelSection title="Hazards on route" icon={ShieldAlert}>
        <RouteHazards route={selectedRoute} hazards={hazards} />
      </PanelSection>
      <PanelSection title="Route guidance" icon={ListOrdered} meta="indicative">
        <NavigationGuidance route={selectedRoute} />
      </PanelSection>
    </>
  ) : (
    <div className="map-panel-section map-panel-empty">
      <RouteIcon size={20} />
      <p>
        No routes yet. Choose an origin and destination in the planner — or use a station or port popup on
        the map — and calculate. Alternatives, hazards and route guidance appear here.
      </p>
    </div>
  );

  const mapCanvas = (
    <div className="map-canvas-wrap">
      <MapContainer
        key={projection}
        /* Must name EPSG3857 explicitly: Leaflet's setOptions copies an
           explicit `undefined` over its own default, leaving the map with
           no CRS at all and throwing inside project(). */
        crs={isPolar ? EPSG3031 : L.CRS.EPSG3857}
        center={view.center}
        zoom={view.zoom}
        minZoom={view.minZoom}
        zoomSnap={view.zoomSnap}
        maxZoom={isPolar ? GIBS_MAX_ZOOM['250m'] : (basemap.maxZoom ?? MAP_DEFAULTS.maxZoom)}
        /* Stop the world repeating sideways forever; the viscosity makes the
           edge push back rather than snap. */
        maxBounds={isPolar ? undefined : MAP_DEFAULTS.maxBounds}
        maxBoundsViscosity={isPolar ? 0 : 0.25}
        worldCopyJump={false}
        style={{ width: '100%', height: '100%', background: 'var(--color-bg-primary)' }}
      >
        {isPolar ? (
          <>
            <GibsLayer key={polarBasemapId} spec={polarBasemap} date={selectedDate} />
            {polarOverlays.seaIce && (
              <GibsLayer spec={POLAR_OVERLAYS.seaIce} date={selectedDate} opacity={POLAR_OVERLAYS.seaIce.opacity} />
            )}
            {polarOverlays.coastlines && (
              <GibsLayer spec={POLAR_OVERLAYS.coastlines} date={selectedDate} opacity={POLAR_OVERLAYS.coastlines.opacity} />
            )}
            {polarOverlays.graticule && (
              <GibsLayer spec={POLAR_OVERLAYS.graticule} date={selectedDate} opacity={POLAR_OVERLAYS.graticule.opacity} />
            )}
          </>
        ) : (
          <TileLayer
            key={basemapId}
            url={basemap.url}
            attribution={basemap.attribution}
            maxZoom={basemap.maxZoom ?? MAP_DEFAULTS.maxZoom}
            opacity={basemap.opacity ?? 1}
            noWrap   /* one Earth, not an infinite strip of them */
          />
        )}

        <CoordinateChips projection={projection} gridShape={grid?.shape} inspect={inspect} />

        {/* Reference geometry: the Antarctic Circle, and the box the model
            actually covers so it's obvious where the data stops. */}
        <Circle
          center={[-90, 0]}
          radius={ANTARCTIC_CIRCLE_RADIUS_M}
          pathOptions={{
            color: 'rgba(11, 127, 168, 0.30)', weight: 1, dashArray: '8 4',
            fillColor: 'rgba(11, 127, 168, 0.04)', fillOpacity: 1,
          }}
          interactive={false}
        />
        <Polyline
          positions={DOMAIN_BOUNDS}
          pathOptions={{ color: 'rgba(11, 127, 168, 0.45)', weight: 1, dashArray: '4 4' }}
          interactive={false}
        >
          <Tooltip sticky>CryoNav domain · 20°W–120°E, 50°S–78°S</Tooltip>
        </Polyline>

        {/* Bathymetry sits under everything else — context, not data. */}
        {layers.bathymetry && grid?.bathy && <BathymetryLayer grid={grid} />}

        {/* Model SIC field: observed, forecast, or the difference between them. */}
        {sicOn && grid && sicMode === 'difference' && diffField && (
          <SicCanvasLayer sic={diffField} grid={grid} colorFn={diffColor} />
        )}
        {sicOn && grid && sicMode === 'forecast' && forecast.data?.sic && (
          <SicCanvasLayer sic={forecast.data.sic} grid={grid} colorFn={sicColor} />
        )}
        {sicOn && grid && sicMode === 'observed' && observed.data?.sic && (
          <SicCanvasLayer sic={observed.data.sic} grid={grid} colorFn={sicColor} />
        )}

        {/* Stations and ports, named on the map, pickable as route endpoints. */}
        {layers.stations && (
          <PlaceMarkers
            stations={RESEARCH_STATIONS}
            ports={DEPARTURE_PORTS}
            config={config}
            originId={origin?.id}
            destinationId={destination?.id}
            onOrigin={pickOrigin}
            onDestination={pickDestination}
            hiddenIds={layers.routes ? [
              routeResult ? routeLastRequest?.origin : origin?.id,
              routeResult ? routeLastRequest?.destination : destination?.id,
            ] : []}
          />
        )}

        {/* Modelled bergs: day-0 positions, drift tracks, projected endpoints
            and the ensemble envelope — flagged when near the selected route. */}
        {layers.icebergs && bergs?.length > 0 && (
          <IcebergLayer
            bergs={bergs}
            horizon={bergHorizon}
            showTracks={Boolean(layers.trajectories)}
            proximity={proximityById}
          />
        )}

        {/* Real CMEMS surface currents and ERA5 wind, as vector fields. */}
        {layers.oceanCurrents && ocean.data?.vectors && (
          <VectorFieldLayer vectors={ocean.data.vectors} color="#6d28d9" scale={26} />
        )}
        {layers.weather && weather.data?.vectors && (
          <VectorFieldLayer vectors={weather.data.vectors} color="#b45309" scale={20} />
        )}

        {/* Observed NIC positions, deliberately distinct from the modelled ones. */}
        {showLiveBergs && liveBergs.data && <LiveIcebergLayer data={liveBergs.data} />}

        {/* Route alternatives, the selected route and its indications. */}
        {layers.routes && (
          <RouteLayer
            result={routeResult}
            exposure={hazards.exposure}
            planned={{ origin, destination }}
          />
        )}
      </MapContainer>

      <SelectedRouteChip
        route={selectedRoute}
        hazards={hazards}
        isCalculating={isCalculating}
        onOpen={narrow ? () => setTab('routes') : undefined}
      />
    </div>
  );

  if (narrow) {
    return (
      <div className="map-workspace is-narrow">
        <aside className="map-panel map-panel-left" aria-label="Planning, routes and layers">
          <div className="map-tabs" role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                className={`map-tab${tab === t.id ? ' is-active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}{t.id === 'routes' && successCount ? ` (${successCount})` : ''}
              </button>
            ))}
          </div>
          {tab === 'plan' && plannerPanel}
          {tab === 'routes' && routesPanel}
          {tab === 'layers' && (
            <>
              {layersPanel}
              <MapLegend />
            </>
          )}
        </aside>
        {mapCanvas}
      </div>
    );
  }

  return (
    <div className="map-workspace">
      <aside className="map-panel map-panel-left" aria-label="Planning and layers">
        {plannerPanel}
        {layersPanel}
      </aside>

      {mapCanvas}

      <aside className="map-panel map-panel-right" aria-label="Routes">
        {routesPanel}
        <MapLegend />
      </aside>
    </div>
  );
}
