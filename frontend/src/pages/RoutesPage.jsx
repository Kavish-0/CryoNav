/* Routes Page — route planning, comparison, guidance and hazards.

   The same components as the map workspace, laid out as a report. The
   selection lives in useRouteStore, so choosing a route here and opening
   the map shows that same route. Wired to POST /route (every alternative
   in one call) and GET /config for the real origin and station list. */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Compass, Route as RouteIcon, Navigation, ShieldAlert, ListOrdered, Map as MapIcon,
} from 'lucide-react';
import { useSelectedRoute } from '@hooks/useSelectedRoute';
import { useRouteHazards } from '@hooks/useRouteHazards';
import RoutePlanner from '@components/routes/RoutePlanner';
import RouteComparison from '@components/routes/RouteComparison';
import RouteMetrics from '@components/routes/RouteMetrics';
import RouteHazards from '@components/routes/RouteHazards';
import NavigationGuidance from '@components/routes/NavigationGuidance';
import '@styles/routes.css';

export default function RoutesPage() {
  const navigate = useNavigate();
  const { result, route } = useSelectedRoute();
  const hazards = useRouteHazards(route, result);
  const hasRoutes = Boolean(result?.list?.length);

  return (
    <div>
      <div className="page-header routes-page-header">
        <div>
          <h1 className="page-title">Route Planning</h1>
          <p className="page-subtitle">
            Time-expanded A* over forecast sea ice and iceberg drift risk — every alternative from one POST /route call
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => navigate('/map')}>
          <MapIcon size={14} /> {hasRoutes ? 'View on map' : 'Open map'}
        </button>
      </div>

      <div className="grid-2" style={{ marginBottom: 'var(--space-4)' }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title"><Compass size={16} /> Voyage Planner</div>
          </div>
          <RoutePlanner />
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title"><Navigation size={16} /> Selected Route</div>
          </div>
          <RouteMetrics route={route} result={result} />
        </div>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-4)' }}>
        <div className="card-header">
          <div className="card-title"><RouteIcon size={16} /> Route Comparison</div>
          {result?.depart_date && (
            <span className="badge badge-blue">
              {result.origin?.name} → {result.destination?.name} · {result.depart_date}
            </span>
          )}
        </div>
        {hasRoutes ? (
          <RouteComparison result={result} variant="table" />
        ) : (
          <div className="empty-state" style={{ padding: 'var(--space-8)' }}>
            <RouteIcon size={32} style={{ color: 'var(--color-text-tertiary)', opacity: 0.4 }} />
            <p className="empty-state-description" style={{ marginTop: 'var(--space-3)' }}>
              Choose an origin and destination, then calculate to run the A* router. Every alternative appears
              here, and the selection is shared with the map.
            </p>
          </div>
        )}
      </div>

      {hasRoutes && (
        <div className="grid-2">
          <div className="card">
            <div className="card-header">
              <div className="card-title"><ListOrdered size={16} /> Route Guidance</div>
              <span className="badge badge-warning">Indicative</span>
            </div>
            <NavigationGuidance route={route} maxVisible={12} onFocusLeg={() => navigate('/map')} />
          </div>

          <div className="card">
            <div className="card-header">
              <div className="card-title"><ShieldAlert size={16} /> Hazards on Route</div>
            </div>
            <RouteHazards route={route} hazards={hazards} />
          </div>
        </div>
      )}
    </div>
  );
}
