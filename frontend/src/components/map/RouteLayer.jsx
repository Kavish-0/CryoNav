/* ═══════════════════════════════════════════════════════════════
   RouteLayer — every computed alternative, with the selected one legible.

     · Alternatives: thin, faded lines in their own colours. Hover
       highlights one (and its card); click selects it.
     · Selected route: white casing plus a heavier line, in a pane above
       the alternatives, with direction arrows spaced by screen distance
       (so they thin out as you zoom out) and numbered leg waypoints that
       are dropped when they would crowd each other.
     · Sea ice on the route: a centre stripe where the observed field along
       the route is ≥ 30%, from hooks/useRouteHazards.
     · Origin and destination pins, from the result — or the planner's
       endpoints before anything has been calculated.

   The map frames the selected route when the selection changes, and the
   focused leg when one is picked in Route Guidance.
   ═══════════════════════════════════════════════════════════════ */

import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Polyline, Marker, Tooltip, LayerGroup, Pane, useMap, useMapEvents,
} from 'react-leaflet';
import L from 'leaflet';
import useRouteStore from '@stores/useRouteStore';
import { getRouteGeometry } from '@utils/navigation';
import { unwrapLongitudes } from '@utils/geo';
import { SIC_ROUTE_BANDS } from '@utils/constants';
import {
  formatNauticalMiles, formatDuration, formatBearing,
} from '@utils/formatters';

const ARROW_SPACING_PX = 140;
const MAX_ARROWS = 28;
const WAYPOINT_MIN_PX = 34;
const DRAWN_BANDS = new Map(SIC_ROUTE_BANDS.filter((b) => b.drawn).map((b) => [b.id, b]));

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);

const ORIGIN_GLYPH = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><circle cx="8" cy="8" r="4" fill="currentColor"/></svg>';
const DESTINATION_GLYPH = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M4 2v12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><path d="M4.8 2.6h8l-2 3 2 3h-8z" fill="currentColor"/></svg>';

function endpointIcon(kind, name, planned) {
  return L.divIcon({
    className: `route-endpoint route-endpoint-${kind}${planned ? ' is-planned' : ''}`,
    html: `<span class="re-pin">${kind === 'origin' ? ORIGIN_GLYPH : DESTINATION_GLYPH}</span>`
      + `<span class="re-label"><em>${kind === 'origin' ? 'Depart' : 'Arrive'}</em>${escapeHtml(name)}</span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

function arrowIcon(angle, color) {
  return L.divIcon({
    className: 'route-arrow-marker',
    html: `<span class="route-arrow" style="--route-color:${color};transform:rotate(${angle.toFixed(1)}deg)">`
      + '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 2 L13.5 13 L8 10 L2.5 13 Z"/></svg></span>',
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function waypointIcon(number, color) {
  return L.divIcon({
    className: 'route-waypoint-marker',
    html: `<span class="route-waypoint" style="--route-color:${color}">${number}</span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

function useZoom() {
  const map = useMap();
  const [zoom, setZoom] = useState(() => map.getZoom());
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) });
  return zoom;
}

/**
 * Arrow positions along a path, evenly spaced in screen pixels at `zoom`.
 * The angle is measured in projected space, so arrows point along the line
 * in either projection.
 */
function arrowsAlong(map, points, zoom) {
  if (points.length < 2) return [];
  const px = points.map(([lat, lon]) => map.project(L.latLng(lat, lon), zoom));
  const cum = [0];
  for (let i = 1; i < px.length; i += 1) cum.push(cum[i - 1] + px[i].distanceTo(px[i - 1]));
  const total = cum[cum.length - 1];
  if (total < 60) return [];

  const spacing = Math.max(ARROW_SPACING_PX, total / MAX_ARROWS);
  const arrows = [];
  let seg = 1;
  for (let d = spacing / 2; d < total; d += spacing) {
    while (seg < cum.length - 1 && cum[seg] < d) seg += 1;
    const a = px[seg - 1];
    const b = px[seg];
    const span = cum[seg] - cum[seg - 1];
    const t = span > 0 ? (d - cum[seg - 1]) / span : 0;
    const ll = map.unproject(L.point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t), zoom);
    arrows.push({
      id: Math.round(d),
      lat: ll.lat,
      lng: ll.lng,
      angle: (Math.atan2(b.x - a.x, -(b.y - a.y)) * 180) / Math.PI,
    });
  }
  return arrows;
}

/** Leg-joining waypoints that are not crowded against the previous one on screen. */
function visibleWaypoints(map, geometry, zoom) {
  const { legs, points } = geometry;
  if (legs.length < 2) return [];
  const out = [];
  let last = map.project(L.latLng(points[0][0], points[0][1]), zoom);
  const end = map.project(L.latLng(points[points.length - 1][0], points[points.length - 1][1]), zoom);

  for (let i = 0; i < legs.length - 1; i += 1) {
    const [lat, lon] = legs[i].positions[legs[i].positions.length - 1];
    const p = map.project(L.latLng(lat, lon), zoom);
    if (p.distanceTo(last) < WAYPOINT_MIN_PX || p.distanceTo(end) < WAYPOINT_MIN_PX) continue;
    out.push({ number: i + 1, lat, lon, arriving: legs[i], departing: legs[i + 1] });
    last = p;
  }
  return out;
}

/** A faded alternative with a wide invisible hit line, so thin lines are easy to hover. */
function AlternativeRoute({ route, positions, hovered, onSelect, onHover }) {
  const lineRef = useRef(null);
  useEffect(() => {
    if (hovered) lineRef.current?.bringToFront();
  }, [hovered]);

  const handlers = {
    click: () => onSelect(route.key),
    mouseover: () => onHover(route.key),
    mouseout: () => onHover(null),
  };

  return (
    <>
      <Polyline
        ref={lineRef}
        positions={positions}
        interactive={false}
        pathOptions={{
          color: route.color,
          weight: hovered ? 4.5 : 2.5,
          opacity: hovered ? 0.95 : 0.45,
          dashArray: route.dashArray || null,
          lineCap: 'round',
          lineJoin: 'round',
        }}
      />
      <Polyline positions={positions} pathOptions={{ color: route.color, weight: 14, opacity: 0 }} eventHandlers={handlers}>
        <Tooltip sticky className="map-tooltip">
          <div className="mt-title" style={{ color: route.color }}>Route {route.letter} · {route.label}</div>
          <div className="mt-row">
            {formatNauticalMiles(route.distanceNm)} · {route.timeH != null ? formatDuration(route.timeH) : '—'}
          </div>
          <div className="mt-dim">Click to select</div>
        </Tooltip>
      </Polyline>
    </>
  );
}

export default function RouteLayer({ result, exposure, planned }) {
  const map = useMap();
  const zoom = useZoom();
  const selectedId = useRouteStore((s) => s.selectedRouteId);
  const hoveredId = useRouteStore((s) => s.hoveredRouteId);
  const focusedLeg = useRouteStore((s) => s.focusedLegIndex);
  const selectRoute = useRouteStore((s) => s.selectRoute);
  const setHoveredRoute = useRouteStore((s) => s.setHoveredRoute);

  const list = result?.list;
  const selected = useMemo(
    () => (list || []).find((r) => r.key === selectedId && r.success) || null,
    [list, selectedId]
  );
  const geometry = useMemo(() => getRouteGeometry(selected), [selected]);

  const alternatives = useMemo(
    () => (list || [])
      .filter((r) => r.success && r.key !== selectedId && r.path.length > 1)
      .map((route) => ({ route, positions: unwrapLongitudes(route.path) })),
    [list, selectedId]
  );

  const arrows = useMemo(
    () => (geometry ? arrowsAlong(map, geometry.points, zoom) : []),
    [map, geometry, zoom]
  );
  const waypoints = useMemo(
    () => (geometry ? visibleWaypoints(map, geometry, zoom) : []),
    [map, geometry, zoom]
  );

  /* Frame the selected route whenever the selection changes. */
  useEffect(() => {
    if (!geometry?.points.length) return;
    map.fitBounds(L.latLngBounds(geometry.points), { padding: [48, 48], maxZoom: 6 });
  }, [map, geometry]);

  /* Frame a focused leg; back to the whole route when the focus is cleared. */
  const leg = geometry && focusedLeg ? geometry.legs[focusedLeg - 1] : null;
  const hadFocus = useRef(false);
  useEffect(() => {
    if (leg) {
      map.fitBounds(L.latLngBounds(leg.positions), { padding: [80, 80], maxZoom: 7 });
      hadFocus.current = true;
    } else if (hadFocus.current && geometry?.points.length) {
      map.fitBounds(L.latLngBounds(geometry.points), { padding: [48, 48], maxZoom: 6 });
      hadFocus.current = false;
    }
  }, [map, leg, geometry]);

  const origin = result?.origin ?? planned?.origin;
  const destination = result?.destination ?? planned?.destination;
  const isPlanned = !result;
  const originIcon = useMemo(
    () => (origin ? endpointIcon('origin', origin.name, isPlanned) : null),
    [origin, isPlanned]
  );
  const destinationIcon = useMemo(
    () => (destination ? endpointIcon('destination', destination.name, isPlanned) : null),
    [destination, isPlanned]
  );

  const iceSegments = selected && exposure
    ? exposure.segments.filter((s) => DRAWN_BANDS.has(s.band))
    : [];

  return (
    <LayerGroup>
      {alternatives.map(({ route, positions }) => (
        <AlternativeRoute
          key={route.key}
          route={route}
          positions={positions}
          hovered={hoveredId === route.key}
          onSelect={selectRoute}
          onHover={setHoveredRoute}
        />
      ))}

      {selected && geometry && (
        <>
          <Pane name="cryonav-route-focus" style={{ zIndex: 430 }}>
            {leg && (
              <Polyline
                positions={leg.positions}
                interactive={false}
                pathOptions={{ color: '#0b7fa8', weight: 16, opacity: 0.28, lineCap: 'round' }}
              />
            )}
          </Pane>

          <Pane name="cryonav-route-selected" style={{ zIndex: 440 }}>
            <Polyline
              positions={geometry.points}
              interactive={false}
              pathOptions={{ color: '#ffffff', weight: 9, opacity: 0.9, lineCap: 'round', lineJoin: 'round' }}
            />
            <Polyline
              positions={geometry.points}
              pathOptions={{
                color: selected.color,
                weight: 5.5,
                opacity: 1,
                dashArray: selected.dashArray || null,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            >
              <Tooltip sticky className="map-tooltip">
                <div className="mt-title" style={{ color: selected.color }}>
                  Route {selected.letter} · {selected.label} (selected)
                </div>
                <div className="mt-row">
                  {formatNauticalMiles(selected.distanceNm)} · {selected.timeH != null ? formatDuration(selected.timeH) : '—'}
                </div>
                <div className="mt-dim">{geometry.legs.length} legs in Route Guidance</div>
              </Tooltip>
            </Polyline>
          </Pane>

          <Pane name="cryonav-route-ice" style={{ zIndex: 445 }}>
            {iceSegments.map((seg) => {
              const band = DRAWN_BANDS.get(seg.band);
              return (
                <Polyline
                  key={`${seg.band}-${Math.round(seg.fromNm)}`}
                  positions={seg.positions}
                  pathOptions={{ color: band.color, weight: 2.5, opacity: 1, lineCap: 'butt' }}
                >
                  <Tooltip sticky className="map-tooltip">
                    <div className="mt-title">{band.label} on route</div>
                    <div className="mt-row">
                      {formatNauticalMiles(seg.toNm - seg.fromNm)} · peak {Math.round((seg.peak ?? 0) * 100)}%
                    </div>
                    <div className="mt-dim">
                      {formatNauticalMiles(seg.fromNm)}–{formatNauticalMiles(seg.toNm)} from departure · observed day-0 ice
                    </div>
                  </Tooltip>
                </Polyline>
              );
            })}
          </Pane>

          {arrows.map((a) => (
            <Marker
              key={`arrow-${a.id}`}
              position={[a.lat, a.lng]}
              icon={arrowIcon(a.angle, selected.color)}
              interactive={false}
              keyboard={false}
            />
          ))}

          {waypoints.map((wp) => (
            <Marker
              key={`wp-${wp.number}`}
              position={[wp.lat, wp.lon]}
              icon={waypointIcon(wp.number, selected.color)}
              keyboard={false}
            >
              <Tooltip className="map-tooltip" direction="top" offset={[0, -8]}>
                <div className="mt-title">Waypoint {wp.number}</div>
                <div className="mt-row">
                  Leg {wp.departing.index}: {formatBearing(wp.departing.bearing)} {wp.departing.compass} ·{' '}
                  {formatNauticalMiles(wp.departing.distanceNm, 1)}
                </div>
                <div className="mt-dim">Indicative — derived from the plotted route</div>
              </Tooltip>
            </Marker>
          ))}
        </>
      )}

      {origin && originIcon && (
        <Marker position={[origin.lat, origin.lon]} icon={originIcon} keyboard={false} zIndexOffset={1000}>
          <Tooltip className="map-tooltip" direction="top" offset={[0, -10]}>
            <div className="mt-title">Origin{isPlanned ? ' (planned)' : ''}</div>
            <div className="mt-row">{origin.name}</div>
          </Tooltip>
        </Marker>
      )}
      {destination && destinationIcon && (
        <Marker position={[destination.lat, destination.lon]} icon={destinationIcon} keyboard={false} zIndexOffset={1000}>
          <Tooltip className="map-tooltip" direction="top" offset={[0, -10]}>
            <div className="mt-title">Destination{isPlanned ? ' (planned)' : ''}</div>
            <div className="mt-row">{destination.name}</div>
          </Tooltip>
        </Marker>
      )}
    </LayerGroup>
  );
}
