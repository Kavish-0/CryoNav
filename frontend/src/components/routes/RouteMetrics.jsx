/* RouteMetrics — the selected route's numbers, as the backend reported them.

   Distance, time, fuel, peak berg risk and hours in ice all come straight
   from POST /route. The only derived values are average speed and ETA
   (from the route's own distance, duration and departure date), and the
   Low / Moderate / High bands, whose thresholds are printed underneath.
   The backend computes no overall route score, so none is shown. */

import React from 'react';
import useRouteStore from '@stores/useRouteStore';
import RiskIndicator from './RiskIndicator';
import { RouteLetter } from './RouteCard';
import { bergRiskLevel, iceExposureLevel } from '@utils/routeAssessment';
import { BERG_RISK_BANDS, ICE_EXPOSURE_BANDS } from '@utils/constants';
import {
  formatNauticalMiles, formatDuration, formatFuel, formatEtaUtc,
} from '@utils/formatters';
import '@styles/routes.css';

const hours = (h) => (h === null || h === undefined ? '—' : `${Number(h).toFixed(1)} h`);

function Tile({ label, value, sub, wide = false }) {
  return (
    <div className={`rm-tile${wide ? ' is-wide' : ''}`}>
      <span className="rm-tile-label">{label}</span>
      <span className="rm-tile-value">{value}</span>
      {sub && <span className="rm-tile-sub">{sub}</span>}
    </div>
  );
}

export default function RouteMetrics({ route, result }) {
  const weights = useRouteStore((s) => s.lastRequest?.weights);

  if (!route) {
    return (
      <p className="route-empty">
        Calculate routes, then select an alternative to see its details.
      </p>
    );
  }

  const avgKn = route.success && route.timeH > 0 ? route.distanceNm / route.timeH : null;
  const eta = route.success ? formatEtaUtc(result?.depart_date, route.timeH) : null;

  return (
    <div className="route-metrics" style={{ '--route-color': route.color }}>
      <div className="rm-head">
        <RouteLetter route={route} />
        <div className="rm-head-text">
          <div className="rm-title">{route.label} route</div>
          <div className="rm-profile">{route.profileName}</div>
        </div>
        {route.recommended && <span className="badge badge-blue">Recommended</span>}
      </div>

      <p className="rm-summary">{route.summary}</p>
      {result?.origin && (
        <div className="rm-voyage">
          {result.origin.name} → {result.destination?.name} · departs {result.depart_date}
          {route.key === 'balanced' && weights && (
            <> · weights time {weights.wTime.toFixed(1)} · fuel {weights.wFuel.toFixed(1)} · risk {weights.wRisk.toFixed(1)}</>
          )}
        </div>
      )}

      {route.success ? (
        <div className="rm-grid">
          <Tile
            label="Distance"
            value={formatNauticalMiles(route.distanceNm)}
            sub={avgKn ? `avg ${avgKn.toFixed(1)} kn` : null}
          />
          <Tile
            label="Estimated time"
            value={route.timeH != null ? formatDuration(route.timeH) : '—'}
            sub={eta ? `ETA ${eta}` : null}
          />
          <Tile
            label="Fuel estimate"
            value={route.fuelT != null ? formatFuel(route.fuelT) : '—'}
            sub="backend fuel model"
          />
          <Tile
            label="Iceberg risk"
            value={<RiskIndicator level={bergRiskLevel(route.maxBergRisk)} />}
            sub={route.maxBergRisk != null ? `peak presence ${Number(route.maxBergRisk).toFixed(3)}` : 'not reported'}
          />
          <Tile
            wide
            label="Sea-ice exposure"
            value={<RiskIndicator level={iceExposureLevel(route.iceHours03, route.iceHours07)} />}
            sub={`${hours(route.iceHours03)} in SIC > 30% · ${hours(route.iceHours07)} in SIC > 70%`}
          />
        </div>
      ) : (
        <div className="alert-card critical">
          <span>No feasible path was found for this profile.</span>
        </div>
      )}

      {route.assessment && (
        <div className={`alert-card ${route.recommended ? 'success' : 'info'} rm-assessment`}>
          <span><strong>Backend assessment:</strong> {route.assessment}</span>
        </div>
      )}

      <p className="rm-footnote">
        Risk bands are display thresholds on backend values. Icebergs: moderate ≥ {BERG_RISK_BANDS.moderate},
        high ≥ {BERG_RISK_BANDS.high} peak presence. Sea ice: high at ≥ {ICE_EXPOSURE_BANDS.highHours07} h in
        SIC &gt; 70%; moderate with any time in SIC &gt; 70% or ≥ {ICE_EXPOSURE_BANDS.moderateHours03} h in
        SIC &gt; 30%. ETA assumes a 00:00 UTC departure.
      </p>
    </div>
  );
}
