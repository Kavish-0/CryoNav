/* RouteHazards — what the selected route runs into.

   Two screens, both computed in the browser from backend data for the
   route's departure date (see hooks/useRouteHazards):
     · Sea ice along the route — the observed field sampled along the path
     · Icebergs near the route — the drift ensembles the router considered,
       checked for same-time proximity and envelope crossings

   Each is labelled as a screen, with its thresholds and data source, so it
   is never mistaken for the router's own risk model. */

import React from 'react';
import { Snowflake, Anchor } from 'lucide-react';
import RiskIndicator from './RiskIndicator';
import { SIC_ROUTE_BANDS, BERG_PROXIMITY_NM } from '@utils/constants';
import { PROXIMITY_LEVELS, describeBergSource } from '@utils/routeAssessment';
import { formatNauticalMiles } from '@utils/formatters';
import '@styles/routes.css';

function SeaIceAlongRoute({ exposure }) {
  if (!exposure.coveredNm) {
    return <p className="rh-note">This route lies outside the model grid, so no sea-ice field covers it.</p>;
  }
  // Open water first, heaviest ice last, so the bar reads left to right
  const bands = [...SIC_ROUTE_BANDS].reverse();
  const covered = exposure.coveredNm;

  return (
    <>
      <div className="rh-bar" role="img" aria-label="Share of the route in each sea-ice band">
        {bands.map((b) => {
          const nm = exposure.bandNm[b.id];
          if (!nm) return null;
          return (
            <span
              key={b.id}
              style={{ width: `${(nm / covered) * 100}%`, background: b.color }}
              title={`${b.label}: ${formatNauticalMiles(nm)}`}
            />
          );
        })}
      </div>
      <div className="rh-bar-legend">
        {bands.map((b) => (exposure.bandNm[b.id] > 0 ? (
          <span key={b.id}>
            <i className="rh-dot" style={{ background: b.color }} />
            {b.label} · {formatNauticalMiles(exposure.bandNm[b.id])}
          </span>
        ) : null))}
      </div>
      <p className="rh-note">
        {exposure.max && exposure.max.value > 0
          ? `Peak ${Math.round(exposure.max.value * 100)}% at ${formatNauticalMiles(exposure.max.atNm)} from departure. `
          : ''}
        {formatNauticalMiles(covered)} of {formatNauticalMiles(exposure.totalNm)} lies inside the model grid,
        sampled every ~{Math.max(1, Math.round(exposure.stepNm))} nm. This is day-0 observed ice; the router
        itself uses the forecast for each day of the passage.
      </p>
    </>
  );
}

function BergRow({ item }) {
  const level = PROXIMITY_LEVELS[item.level];
  const parts = [];
  if (item.closest) {
    parts.push(`closest ≈ ${formatNauticalMiles(item.closest.clearanceNm)} at T+${Math.round(item.closest.hour)} h`);
  } else {
    parts.push('drift horizon ends before the passage');
  }
  if (item.envelope) {
    parts.push(item.envelope.edgeNm <= 0
      ? 'route crosses 2σ envelope'
      : `envelope ${formatNauticalMiles(item.envelope.edgeNm)} off`);
  }

  return (
    <li className="rh-berg">
      <RiskIndicator level={level.risk} label={level.label} />
      <span className="rh-berg-id">{item.bergId}</span>
      <span className="rh-berg-detail">{parts.join(' · ')}</span>
    </li>
  );
}

export default function RouteHazards({ route, hazards }) {
  if (!route?.success || !hazards?.active) {
    return <p className="route-empty">Select a route that found a path to screen it for sea ice and icebergs.</p>;
  }

  const {
    exposure, proximity, loading, errors, departDate, horizonDays, bergLimit, bergSource, nEnsemble,
  } = hazards;
  const flagged = (proximity || []).filter((p) => p.level !== 'clear').length;
  const source = describeBergSource(bergSource);

  return (
    <div className="route-hazards">
      <section className="rh-section">
        <div className="rh-title">
          <span><Snowflake size={11} /> Sea ice along route</span>
          <span className="rh-title-meta">observed {departDate}</span>
        </div>
        {loading.sic && <p className="rh-note">Sampling sea ice along the route…</p>}
        {errors.sic && <p className="rh-note">Sea-ice field unavailable (GET /observed or /grid failed).</p>}
        {exposure && <SeaIceAlongRoute exposure={exposure} />}
      </section>

      <section className="rh-section">
        <div className="rh-title">
          <span><Anchor size={11} /> Icebergs near route</span>
          {proximity && <span className="rh-title-meta">{flagged} of {proximity.length} flagged</span>}
        </div>
        {loading.bergs && <p className="rh-note">Propagating berg drift over the passage…</p>}
        {errors.bergs && <p className="rh-note">Iceberg drift unavailable (GET /bergs failed).</p>}
        {proximity && proximity.length === 0 && (
          <p className="rh-note">No tracked bergs returned for {departDate}.</p>
        )}
        {proximity && proximity.length > 0 && (
          <ul className="rh-bergs">
            {proximity.map((item) => <BergRow key={item.bergId} item={item} />)}
          </ul>
        )}
        {source && <span className={`badge badge-${source.tone} rh-source`}>{source.label}</span>}
        <p className="rh-note">
          Screens the {bergLimit} largest bergs the router considered ({nEnsemble ?? '—'}-member drift over
          {' '}{horizonDays} d). <strong>Danger</strong>: within {BERG_PROXIMITY_NM.danger} nm at the same moment
          (ship at uniform speed; berg centre less half its length), or the route crosses the berg&apos;s 2σ
          envelope. <strong>Caution</strong>: drift track within {BERG_PROXIMITY_NM.caution} nm at any time.
          Geometric screening in the browser — not the backend&apos;s berg-risk field.
        </p>
      </section>
    </div>
  );
}
