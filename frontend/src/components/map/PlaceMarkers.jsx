/* ═══════════════════════════════════════════════════════════════
   PlaceMarkers — research stations and departure ports, with names
   permanently on the map.

   These are divIcon labels, matching the bundled web/ client: flag + name
   for stations, anchor + name for ports, in two colours so the two kinds
   never get confused. The current origin and destination are outlined.

   Only places the router actually knows can be set as an endpoint — the
   API takes named keys, so the buttons appear only where the live /config
   says the backend will accept them. Picking an end calculates routes as
   soon as both ends are set, as the web/ client does.
   ═══════════════════════════════════════════════════════════════ */

import React, { useMemo } from 'react';
import { Marker, Popup, LayerGroup, useMap } from 'react-leaflet';
import L from 'leaflet';

/** Label pill anchored to the left of the point, like main's map. */
function labelIcon(text, kind, role) {
  return L.divIcon({
    className: `place-marker place-${kind}${role ? ` is-${role}` : ''}`,
    html: `<span class="place-label">${text}</span>`,
    iconSize: null,
    iconAnchor: [46, 12],
  });
}

function PlacePopup({ place, kind, role, routable, onOrigin, onDestination }) {
  const map = useMap();
  const pick = (handler) => {
    map.closePopup();
    handler(place);
  };

  return (
    <Popup>
      <div className="map-popup">
        <strong className={`mp-title ${kind === 'port' ? 'is-port' : ''}`}>
          {kind === 'port' ? place.icon : place.flag} {place.name}
        </strong>
        <div className="mp-source">
          {kind === 'port' ? `Port · ${place.country}` : place.operator}
        </div>
        <div className="mp-rows">
          {Math.abs(place.lat).toFixed(2)}°S, {Math.abs(place.lon).toFixed(2)}°
          {place.lon < 0 ? 'W' : 'E'}
        </div>
        {routable ? (
          <>
            {role && <div className="mp-role">{role === 'origin' ? 'Current origin' : 'Current destination'}</div>}
            <div className="mp-actions">
              <button
                type="button" className="btn btn-secondary btn-sm"
                disabled={role === 'origin'} onClick={() => pick(onOrigin)}
              >
                Depart from here
              </button>
              <button
                type="button" className="btn btn-primary btn-sm"
                disabled={role === 'destination'} onClick={() => pick(onDestination)}
              >
                Route to here
              </button>
            </div>
            <div className="mp-hint">Routes are calculated once both ends are set.</div>
          </>
        ) : (
          <div className="mp-source" style={{ marginTop: 6 }}>
            Not a routable endpoint in this build
          </div>
        )}
      </div>
    </Popup>
  );
}

export default function PlaceMarkers({
  stations, ports, config, originId, destinationId, onOrigin, onDestination, hiddenIds = [],
}) {
  /* Places already marked by the route's own origin/destination pins are
     skipped, so two labels never sit on the same point. */
  const hidden = new Set(hiddenIds.filter(Boolean));
  const visibleStations = (stations || []).filter((s) => !hidden.has(s.id));
  const visiblePorts = (ports || []).filter((p) => !hidden.has(p.id));

  /* The backend only routes between the origins/stations it declares in
     config, so check each place against the live config rather than
     assuming every pin on the map is selectable. */
  const routableIds = useMemo(() => {
    const ids = new Set();
    Object.keys(config?.stations || {}).forEach((k) => ids.add(k));
    Object.keys(config?.origins || {}).forEach((k) => ids.add(k));
    return ids;
  }, [config]);

  const roleOf = (id) => (id === originId ? 'origin' : id === destinationId ? 'destination' : null);

  /* Icons are rebuilt only when the endpoints change, not on every map render. */
  const icons = useMemo(() => {
    const map = new Map();
    (stations || []).forEach((s) => map.set(`st-${s.id}`, labelIcon(`${s.flag} ${s.name}`, 'station', roleOf(s.id))));
    (ports || []).forEach((p) => map.set(`pt-${p.id}`, labelIcon(`${p.icon} ${p.name}`, 'port', roleOf(p.id))));
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stations, ports, originId, destinationId]);

  return (
    <LayerGroup>
      {visibleStations.map((s) => (
        <Marker key={`st-${s.id}`} position={[s.lat, s.lon]} icon={icons.get(`st-${s.id}`)}>
          <PlacePopup
            place={s} kind="station" role={roleOf(s.id)} routable={routableIds.has(s.id)}
            onOrigin={onOrigin} onDestination={onDestination}
          />
        </Marker>
      ))}

      {visiblePorts.map((p) => (
        <Marker key={`pt-${p.id}`} position={[p.lat, p.lon]} icon={icons.get(`pt-${p.id}`)}>
          <PlacePopup
            place={p} kind="port" role={roleOf(p.id)} routable={routableIds.has(p.id)}
            onOrigin={onOrigin} onDestination={onDestination}
          />
        </Marker>
      ))}
    </LayerGroup>
  );
}
