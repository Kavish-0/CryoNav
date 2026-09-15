/* RouteCard — one computed alternative, selectable.

   Shows the backend's headline numbers and two risk pills. Hovering marks
   the route on the map; clicking selects it everywhere via useRouteStore. */

import React from 'react';
import { AlertTriangle } from 'lucide-react';
import RiskIndicator from './RiskIndicator';
import { bergRiskLevel, iceExposureLevel } from '@utils/routeAssessment';
import { formatNauticalMiles, formatDuration, formatFuel } from '@utils/formatters';
import '@styles/routes.css';

/** The route's letter in its own colour — the same mark used on the map. */
export function RouteLetter({ route }) {
  return (
    <span className="route-letter" style={{ '--route-color': route.color }} aria-hidden="true">
      {route.letter}
    </span>
  );
}

export default function RouteCard({ route, selected = false, onSelect, onHover }) {
  const selectable = route.success;

  return (
    <button
      type="button"
      className={`route-card${selected ? ' is-selected' : ''}${selectable ? '' : ' is-failed'}`}
      style={{ '--route-color': route.color }}
      onClick={() => selectable && onSelect?.(route.key)}
      onMouseEnter={() => onHover?.(route.key)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(route.key)}
      onBlur={() => onHover?.(null)}
      aria-pressed={selected}
      aria-disabled={!selectable}
      title={route.profileName}
    >
      <RouteLetter route={route} />
      <span className="rc-body">
        <span className="rc-title">
          <span className="rc-name">Route {route.letter} · {route.label}</span>
          {route.recommended && <span className="badge badge-blue rc-rec">Recommended</span>}
        </span>

        {route.success ? (
          <>
            <span className="rc-stats">
              <span>{formatNauticalMiles(route.distanceNm)}</span>
              <span>{route.timeH != null ? formatDuration(route.timeH) : '—'}</span>
              <span>{route.fuelT != null ? formatFuel(route.fuelT) : '—'}</span>
            </span>
            <span className="rc-risks">
              <RiskIndicator prefix="Ice" level={iceExposureLevel(route.iceHours03, route.iceHours07)} />
              <RiskIndicator prefix="Bergs" level={bergRiskLevel(route.maxBergRisk)} />
            </span>
          </>
        ) : (
          <span className="rc-failed">
            <AlertTriangle size={11} /> No feasible path for this profile
          </span>
        )}
      </span>
    </button>
  );
}
