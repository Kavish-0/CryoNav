/* RouteComparison — every alternative from one POST /route call.

   Two presentations of the same store-backed selection:
     cards — compact list for the map workspace
     table — the backend's comparison columns, for the Routes page

   Column labels and order come from the response's comparison.headers;
   values come from the normalized routes, which carry the full-journey
   numbers (including the open-water legs to and from port). */

import React from 'react';
import { CheckCircle2, AlertTriangle } from 'lucide-react';
import useRouteStore from '@stores/useRouteStore';
import RouteCard, { RouteLetter } from './RouteCard';
import { describeForecastSource, describeBergSource } from '@utils/routeAssessment';
import { formatNauticalMiles, formatDuration, formatFuel } from '@utils/formatters';
import '@styles/routes.css';

const DEFAULT_HEADERS = [
  { key: 'profile', label: 'Route', align: 'left' },
  { key: 'distance_nm', label: 'Distance (nm)', align: 'right' },
  { key: 'time_h', label: 'Time (h)', align: 'right' },
  { key: 'ice_hours_03', label: 'SIC>30% (h)', align: 'right' },
  { key: 'ice_hours_07', label: 'SIC>70% (h)', align: 'right' },
  { key: 'fuel_t', label: 'Fuel (t)', align: 'right' },
  { key: 'max_berg_risk', label: 'Max Berg Risk', align: 'right' },
];

/** Backend column key → normalized route field. */
const FIELD_FOR = {
  distance_nm: 'distanceNm',
  time_h: 'timeH',
  fuel_t: 'fuelT',
  ice_hours_03: 'iceHours03',
  ice_hours_07: 'iceHours07',
  max_berg_risk: 'maxBergRisk',
};

function formatCell(key, value) {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  switch (key) {
    case 'distance_nm': return formatNauticalMiles(value);
    case 'time_h': return formatDuration(value);
    case 'fuel_t': return formatFuel(value);
    case 'ice_hours_03':
    case 'ice_hours_07': return `${Number(value).toFixed(1)} h`;
    case 'max_berg_risk': return Number(value).toFixed(3);
    default: return String(value);
  }
}

/** Which forecast and which berg dataset the router actually used. */
export function RouteSources({ result }) {
  const items = [
    describeForecastSource(result?.forecast_source),
    describeBergSource(result?.berg_source),
  ].filter(Boolean);
  if (!items.length) return null;
  return (
    <div className="route-sources">
      {items.map((s) => (
        <span key={s.label} className={`badge badge-${s.tone}`}>{s.label}</span>
      ))}
    </div>
  );
}

export default function RouteComparison({ result, variant = 'cards' }) {
  const selectedId = useRouteStore((s) => s.selectedRouteId);
  const selectRoute = useRouteStore((s) => s.selectRoute);
  const setHoveredRoute = useRouteStore((s) => s.setHoveredRoute);
  const list = result?.list || [];
  if (!list.length) return null;

  if (variant === 'cards') {
    return (
      <div className="route-comparison">
        <div className="route-cards" role="list">
          {list.map((route) => (
            <RouteCard
              key={route.key}
              route={route}
              selected={route.key === selectedId}
              onSelect={selectRoute}
              onHover={setHoveredRoute}
            />
          ))}
        </div>
        <RouteSources result={result} />
      </div>
    );
  }

  const headers = result.comparison?.headers?.length ? result.comparison.headers : DEFAULT_HEADERS;
  const assessed = list.filter((r) => r.assessment);

  return (
    <div className="route-comparison">
      <div className="table-scroll">
        <table className="table route-table">
          <thead>
            <tr>
              {headers.map((h) => (
                <th key={h.key} style={{ textAlign: h.align }}>{h.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.map((route) => {
              const selected = route.key === selectedId;
              return (
                <tr
                  key={route.key}
                  className={`${route.success ? 'is-selectable' : 'is-failed'}${selected ? ' is-selected' : ''}`}
                  onClick={() => route.success && selectRoute(route.key)}
                  onMouseEnter={() => setHoveredRoute(route.key)}
                  onMouseLeave={() => setHoveredRoute(null)}
                  aria-selected={selected}
                >
                  {headers.map((h) => (
                    <td key={h.key} style={{ textAlign: h.align }}>
                      {h.key === 'profile' ? (
                        <span className="route-name">
                          <RouteLetter route={route} />
                          {route.success
                            ? <CheckCircle2 size={13} className="rt-ok" />
                            : <AlertTriangle size={13} className="rt-fail" />}
                          <span>{route.label}</span>
                          {route.recommended && <span className="badge badge-blue rc-rec">Recommended</span>}
                        </span>
                      ) : (
                        formatCell(h.key, route.success ? route[FIELD_FOR[h.key]] : null)
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <RouteSources result={result} />

      {assessed.length > 0 && (
        <div className="route-assessments">
          {assessed.map((r) => (
            <div key={r.key} className={`alert-card ${r.recommended ? 'success' : r.success ? 'info' : 'warning'}`}>
              <span><strong>{r.letter} · {r.label}:</strong> {r.assessment}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
