/* NavigationGuidance — route legs derived from the selected route.

   Headings, distances and course alterations are calculated from the
   route polyline POST /route returned (utils/navigation.buildRouteGeometry).
   The backend provides no waypoints or headings of its own, so this is
   labelled as indicative route guidance for decision support — not
   certified navigational instruction.

   Clicking a leg focuses it on the map through useRouteStore. */

import React, { useEffect, useState } from 'react';
import { Compass } from 'lucide-react';
import useRouteStore from '@stores/useRouteStore';
import { getRouteGeometry } from '@utils/navigation';
import {
  formatBearing, formatNauticalMiles, formatCoords,
} from '@utils/formatters';
import '@styles/routes.css';

/** Course alterations smaller than this are not called out. */
const MIN_TURN_DEG = 5;

function HeadingArrow({ bearing }) {
  return (
    <span className="nl-arrow" style={{ transform: `rotate(${bearing}deg)` }} aria-hidden="true">
      <svg viewBox="0 0 16 16" width="14" height="14">
        <path d="M8 1.5 L13 13.5 L8 10.5 L3 13.5 Z" fill="currentColor" />
      </svg>
    </span>
  );
}

export default function NavigationGuidance({ route, maxVisible = 8, onFocusLeg }) {
  const focusedLeg = useRouteStore((s) => s.focusedLegIndex);
  const focusLeg = useRouteStore((s) => s.focusLeg);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => { setShowAll(false); }, [route?.key]);

  const geometry = getRouteGeometry(route);
  if (!route?.success || !geometry?.legs.length) {
    return <p className="route-empty">Select a route that found a path to see its legs.</p>;
  }

  const { legs, totalNm, toleranceNm } = geometry;
  const visible = showAll ? legs : legs.slice(0, maxVisible);

  return (
    <div className="nav-guidance" style={{ '--route-color': route.color }}>
      <p className="nav-guidance-disclaimer">
        <strong>Indicative only.</strong> Headings and leg lengths are derived from the plotted route for
        decision support. Not certified navigational guidance — verify against official charts, ice
        services and the vessel&apos;s bridge systems.
      </p>

      <ol className="nav-legs">
        {visible.map((leg) => {
          const focused = focusedLeg === leg.index;
          const turn = leg.turnDeg !== null && Math.abs(leg.turnDeg) >= MIN_TURN_DEG
            ? `Alter ${Math.round(Math.abs(leg.turnDeg))}° to ${leg.turnDeg > 0 ? 'starboard' : 'port'}`
            : null;
          return (
            <li key={leg.index} className={`nav-leg${focused ? ' is-focused' : ''}`}>
              <button
                type="button"
                className="nav-leg-btn"
                onClick={() => {
                  focusLeg(focused ? null : leg.index);
                  if (!focused) onFocusLeg?.(leg.index);
                }}
                aria-pressed={focused}
                title={focused ? 'Show the whole route' : 'Show this leg on the map'}
              >
                <span className="nl-num">Leg {leg.index}</span>
                <span className="nl-heading">
                  <HeadingArrow bearing={leg.bearing} />
                  {formatBearing(leg.bearing)} {leg.compass}
                </span>
                <span className="nl-dist">{formatNauticalMiles(leg.distanceNm, 1)}</span>
                <span className="nl-coords">
                  {formatCoords(leg.start.lat, leg.start.lon)} → {formatCoords(leg.end.lat, leg.end.lon)}
                </span>
                <span className="nl-meta">
                  <span className="nl-turn">{turn ?? (leg.index === 1 ? 'Departure heading' : 'Hold course')}</span>
                  <span>{formatNauticalMiles(leg.endNm)} from departure</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {legs.length > maxVisible && (
        <button type="button" className="btn btn-ghost btn-sm nav-show-all" onClick={() => setShowAll((v) => !v)}>
          {showAll ? 'Show fewer legs' : `Show all ${legs.length} legs`}
        </button>
      )}

      <p className="nav-guidance-foot">
        <Compass size={10} /> {legs.length} legs · {formatNauticalMiles(totalNm)} measured along the plotted
        path (backend total {formatNauticalMiles(route.distanceNm)}). Initial great-circle headings, degrees
        true; legs stay within ±{Math.round(toleranceNm)} nm of the plotted route.
      </p>
    </div>
  );
}
