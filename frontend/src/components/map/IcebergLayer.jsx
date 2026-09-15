/* ═══════════════════════════════════════════════════════════════
   IcebergLayer — the full iceberg picture, ported from web/app.js.

   For each berg this renders four things, which together are the point
   of the whole drift model:

     · Day 0 marker — where the berg actually is, with a radar pulse
     · Drift track — the mean_track polyline out to the horizon
     · Projected endpoint — where it is predicted to be at +N days,
       labelled with net displacement from Day 0
     · Ensemble ellipse — 2σ of the Monte Carlo spread at the final step,
       i.e. the honest uncertainty around that prediction

   Showing the prediction without the spread would overstate what the
   physics can actually tell you, which is why the ellipse is not
   optional decoration.

   When a route is selected, `proximity` (from hooks/useRouteHazards) marks
   bergs the route screen flagged: red for danger, amber for caution.
   ═══════════════════════════════════════════════════════════════ */

import React, { useMemo } from 'react';
import { Marker, Polyline, Circle, Tooltip, LayerGroup } from 'react-leaflet';
import L from 'leaflet';
import { ensembleSpread, displacementKm } from '@utils/navigation';
import { formatNauticalMiles } from '@utils/formatters';

const TRACK_COLOR = '#c98a00';
const LEVEL_STYLE = {
  clear: { fill: '#0b7fa8', shade: '#075f7f', ring: TRACK_COLOR },
  caution: { fill: '#b45309', shade: '#7c3a06', ring: '#b45309' },
  danger: { fill: '#c62828', shade: '#8e1c1c', ring: '#c62828' },
};
const LEVEL_LABEL = { danger: 'Danger', caution: 'Caution', clear: 'Clear' };

/** Day-0 berg marker: pulsing radar ring behind an ice-floe glyph. */
function bergIcon(level) {
  const style = LEVEL_STYLE[level] || LEVEL_STYLE.clear;
  const flag = level === 'danger' || level === 'caution' ? ` is-${level}` : '';
  return L.divIcon({
    className: 'berg-marker',
    html: `
      <div class="berg-marker-inner${flag}">
        <span class="berg-radar-pulse"></span>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <polygon points="12,2 22,20 16,22 12,18 8,22 2,20"
                   fill="${style.fill}" stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
          <polygon points="12,2 16,22 12,18" fill="${style.shade}" opacity="0.75"/>
        </svg>
      </div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

const BERG_ICONS = {
  clear: bergIcon('clear'),
  caution: bergIcon('caution'),
  danger: bergIcon('danger'),
};

/** Projected-position marker carrying a "+Nd" flag. */
function endIcon(days) {
  return L.divIcon({
    className: 'berg-target-marker',
    html: `
      <div class="berg-target-inner">
        <span class="berg-target-dot"></span>
        <span class="berg-target-flag">+${days}d</span>
      </div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

/** One line on the berg tooltip saying how it relates to the selected route. */
function RouteScreen({ item }) {
  if (!item) return null;
  const detail = item.closest
    ? `closest ≈ ${formatNauticalMiles(item.closest.clearanceNm)} at T+${Math.round(item.closest.hour)} h`
    : `track within ${formatNauticalMiles(item.minTrackNm)}`;
  return (
    <div className={`mt-screen mt-${item.level}`}>
      Selected route: {LEVEL_LABEL[item.level]} · {detail}
    </div>
  );
}

export default function IcebergLayer({ bergs, horizon = 7, showTracks = true, proximity = null }) {
  const prepared = useMemo(
    () => (bergs || [])
      .filter((b) => b.mean_track?.length)
      .map((berg) => {
        const track = berg.mean_track;
        const [, startLat, startLon] = track[0];
        const [lastDay, endLat, endLon] = track[track.length - 1];
        return {
          berg,
          startLat,
          startLon,
          endLat,
          endLon,
          days: lastDay || horizon,
          path: track.map((p) => [p[1], p[2]]),
          driftKm: displacementKm(startLat, startLon, endLat, endLon),
          spread: ensembleSpread(berg.ensemble),
        };
      }),
    [bergs, horizon]
  );

  return (
    <LayerGroup>
      {prepared.map((p) => {
        const screen = proximity?.get(p.berg.berg_id) ?? null;
        const level = screen?.level ?? 'clear';
        const style = LEVEL_STYLE[level];

        return (
          <React.Fragment key={p.berg.berg_id}>
            {/* Day 0 */}
            <Marker position={[p.startLat, p.startLon]} icon={BERG_ICONS[level]}>
              <Tooltip sticky className="map-tooltip">
                <div className="mt-title">Iceberg {p.berg.berg_id} · Day 0</div>
                <div className="mt-row">
                  {Math.round(p.berg.length_m)} m × {Math.round(p.berg.width_m)} m
                </div>
                <div className="mt-dim">
                  {Math.abs(p.startLat).toFixed(2)}°S, {Math.abs(p.startLon).toFixed(2)}°
                  {p.startLon < 0 ? 'W' : 'E'}
                </div>
                {p.berg.observed_on && (
                  <div className="mt-dim">Observed {p.berg.observed_on}</div>
                )}
                <RouteScreen item={screen} />
              </Tooltip>
            </Marker>

            {showTracks && p.path.length > 1 && (
              <>
                {/* Drift track */}
                <Polyline
                  positions={p.path}
                  pathOptions={{ color: TRACK_COLOR, weight: 2, opacity: 0.85, dashArray: '5 3' }}
                />

                {/* Projected endpoint */}
                <Marker position={[p.endLat, p.endLon]} icon={endIcon(p.days)}>
                  <Tooltip sticky className="map-tooltip">
                    <div className="mt-title">Day +{p.days} projected</div>
                    <div className="mt-row">Berg {p.berg.berg_id}</div>
                    <div className="mt-dim">
                      {Math.abs(p.endLat).toFixed(2)}°S, {Math.abs(p.endLon).toFixed(2)}°
                      {p.endLon < 0 ? 'W' : 'E'}
                    </div>
                    <div className="mt-accent">Net drift {p.driftKm.toFixed(0)} km</div>
                  </Tooltip>
                </Marker>

                {/* Monte Carlo uncertainty */}
                {p.spread && (
                  <Circle
                    center={[p.spread.lat, p.spread.lon]}
                    radius={p.spread.radius}
                    pathOptions={{
                      color: style.ring,
                      opacity: level === 'clear' ? 0.5 : 0.85,
                      fillColor: style.ring,
                      fillOpacity: level === 'clear' ? 0.08 : 0.14,
                      weight: level === 'clear' ? 1.5 : 2,
                      dashArray: '4 4',
                    }}
                  >
                    <Tooltip className="map-tooltip">
                      <div className="mt-title">Drift uncertainty</div>
                      <div className="mt-dim">
                        2σ of {p.berg.ensemble?.length ?? 0} ensemble members at day +{p.days}
                      </div>
                      <RouteScreen item={screen} />
                    </Tooltip>
                  </Circle>
                )}
              </>
            )}
          </React.Fragment>
        );
      })}
    </LayerGroup>
  );
}
