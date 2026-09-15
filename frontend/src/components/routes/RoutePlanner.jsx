/* RoutePlanner — voyage setup for POST /route.

   Every control here is a real input. Origin and destination come from
   GET /config; the departure date is the app's analysis date (so the map
   shows the same day the route departs); berg_limit feeds the router's
   risk field; the cost weights are applied by the backend to the Balanced
   profile (the other profiles stay fixed references); and the priority
   picks which computed alternative is selected. */

import React, { useEffect, useMemo, useState } from 'react';
import {
  MapPin, Flag, ArrowUpDown, Route as RouteIcon, CalendarDays, Anchor, Loader2, X,
  SlidersHorizontal, RotateCcw,
} from 'lucide-react';
import useRouteStore from '@stores/useRouteStore';
import useAppStore from '@stores/useAppStore';
import { useConfig, useDemoDates } from '@hooks/useConfig';
import { usePlanRoutes } from '@hooks/useRouteCalculation';
import { ROUTE_PRIORITIES } from '@utils/constants';
import '@styles/routes.css';

/* Store keys → POST /route body keys and labels. */
const WEIGHT_FIELDS = [
  { key: 'wTime', body: 'w_time', label: 'Time' },
  { key: 'wFuel', body: 'w_fuel', label: 'Fuel' },
  { key: 'wRisk', body: 'w_risk', label: 'Ice / berg risk' },
];

const toWaypoints = (dict, kind) =>
  Object.entries(dict || {}).map(([id, w]) => ({ id, kind, name: w.name || id, lat: w.lat, lon: w.lon }));

function WaypointSelect({ id, value, onChange, ports, stations, disabled }) {
  return (
    <select
      id={id}
      className="rp-select"
      value={value?.id || ''}
      disabled={disabled}
      onChange={(e) => onChange([...ports, ...stations].find((w) => w.id === e.target.value) || null)}
    >
      {!value && <option value="">Select…</option>}
      <optgroup label="Ports & waypoints">
        {ports.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </optgroup>
      <optgroup label="Research stations">
        {stations.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </optgroup>
    </select>
  );
}

export default function RoutePlanner() {
  const { data: config, isLoading: configLoading, isError: configError } = useConfig();
  const { data: dates } = useDemoDates();

  const selectedDate = useAppStore((s) => s.selectedDate);
  const setSelectedDate = useAppStore((s) => s.setSelectedDate);

  const origin = useRouteStore((s) => s.origin);
  const destination = useRouteStore((s) => s.destination);
  const setOrigin = useRouteStore((s) => s.setOrigin);
  const setDestination = useRouteStore((s) => s.setDestination);
  const swapEndpoints = useRouteStore((s) => s.swapEndpoints);
  const preferredProfile = useRouteStore((s) => s.preferredProfile);
  const setPreferredProfile = useRouteStore((s) => s.setPreferredProfile);
  const bergLimit = useRouteStore((s) => s.bergLimit);
  const setBergLimit = useRouteStore((s) => s.setBergLimit);
  const costWeights = useRouteStore((s) => s.costWeights);
  const setCostWeight = useRouteStore((s) => s.setCostWeight);
  const hasRoutes = useRouteStore((s) => Boolean(s.routes));
  const lastRequest = useRouteStore((s) => s.lastRequest);
  const calculationError = useRouteStore((s) => s.calculationError);
  const clearRoutes = useRouteStore((s) => s.clearRoutes);

  const { plan, isCalculating } = usePlanRoutes();

  const ports = useMemo(() => toWaypoints(config?.origins, 'port'), [config]);
  const stations = useMemo(() => toWaypoints(config?.stations, 'station'), [config]);

  /* Default endpoints to the backend's own RouteRequest defaults once the
     real waypoint list has loaded. */
  useEffect(() => {
    const all = [...ports, ...stations];
    if (!all.length) return;
    const state = useRouteStore.getState();
    if (!state.origin) setOrigin(all.find((w) => w.id === 'cape_town') || ports[0] || all[0]);
    if (!state.destination) setDestination(all.find((w) => w.id === 'bharati') || stations[0] || all[1]);
  }, [ports, stations, setOrigin, setDestination]);

  /* Elapsed-time readout: a cold A* run takes long enough that a static
     "Calculating…" looks like a hang. */
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!isCalculating) { setElapsed(0); return undefined; }
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [isCalculating]);

  const sameEndpoints = Boolean(origin && destination && origin.id === destination.id);
  const stale = Boolean(hasRoutes && lastRequest && (
    lastRequest.origin !== origin?.id
    || lastRequest.destination !== destination?.id
    || lastRequest.departDate !== selectedDate
    || lastRequest.bergLimit !== bergLimit
    || WEIGHT_FIELDS.some(({ key }) => lastRequest.weights?.[key] !== costWeights[key])
  ));
  const range = dates?.range;
  const defaults = config?.routing_weights;
  const atDefaults = !defaults || WEIGHT_FIELDS.every(({ key, body }) => costWeights[key] === defaults[body]);

  return (
    <div className="route-planner">
      {configError && (
        <div className="alert-card warning">
          <span>Could not load /config — is the CryoNav backend running at the configured API URL?</span>
        </div>
      )}

      <div className="rp-field">
        <label className="rp-label" htmlFor="rp-origin"><MapPin size={11} /> Origin</label>
        <WaypointSelect
          id="rp-origin" value={origin} onChange={setOrigin}
          ports={ports} stations={stations} disabled={configLoading || !ports.length}
        />
      </div>

      <div className="rp-swap-row">
        <button
          type="button" className="btn btn-ghost btn-sm" onClick={swapEndpoints}
          disabled={!origin || !destination} title="Swap origin and destination"
        >
          <ArrowUpDown size={12} /> Swap
        </button>
      </div>

      <div className="rp-field">
        <label className="rp-label" htmlFor="rp-destination"><Flag size={11} /> Destination</label>
        <WaypointSelect
          id="rp-destination" value={destination} onChange={setDestination}
          ports={ports} stations={stations} disabled={configLoading || !stations.length}
        />
      </div>

      <div className="rp-field">
        <label className="rp-label" htmlFor="rp-date"><CalendarDays size={11} /> Departure date</label>
        <input
          id="rp-date" type="date" className="rp-input"
          value={selectedDate} min={range?.start} max={range?.end}
          onChange={(e) => e.target.value && setSelectedDate(e.target.value)}
        />
        {dates?.demo_dates?.length > 0 && (
          <div className="rp-chips" aria-label="Held-out test dates">
            {dates.demo_dates.map((d) => (
              <button
                key={d} type="button"
                className={`rp-chip${d === selectedDate ? ' is-active' : ''}`}
                onClick={() => setSelectedDate(d)}
                title="Held-out date the forecast model never trained on"
              >
                {d}
              </button>
            ))}
          </div>
        )}
        <p className="rp-note">Also the map&apos;s analysis date, so layers show the day of departure.</p>
      </div>

      <div className="rp-field">
        <span className="rp-label" id="rp-priority-label">Priority</span>
        <div className="rp-segmented" role="radiogroup" aria-labelledby="rp-priority-label">
          {ROUTE_PRIORITIES.map((p) => (
            <button
              key={p.id} type="button" role="radio" aria-checked={preferredProfile === p.id}
              className={`rp-seg${preferredProfile === p.id ? ' is-active' : ''}`}
              onClick={() => setPreferredProfile(p.id)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p className="rp-note">Every alternative is always computed; this picks which one is selected.</p>
      </div>

      <div className="rp-field">
        <label className="rp-label" htmlFor="rp-bergs"><Anchor size={11} /> Icebergs in risk field</label>
        <div className="rp-range-row">
          <input
            id="rp-bergs" type="range" min={1} max={20} step={1} value={bergLimit}
            onChange={(e) => setBergLimit(Number(e.target.value))}
          />
          <span className="rp-range-value">{bergLimit}</span>
        </div>
        <p className="rp-note">Largest tracked bergs propagated into the router&apos;s berg-risk field.</p>
      </div>

      <div className="rp-field">
        <span className="rp-label"><SlidersHorizontal size={11} /> Route A (Balanced) weights</span>
        {WEIGHT_FIELDS.map(({ key, label }) => (
          <div className="rp-range-row" key={key}>
            <label className="rp-weight-label" htmlFor={`rp-${key}`}>{label}</label>
            <input
              id={`rp-${key}`} type="range" min={0} max={5} step={0.1} value={costWeights[key]}
              onChange={(e) => setCostWeight(key, Number(e.target.value))}
            />
            <span className="rp-range-value">{costWeights[key].toFixed(1)}</span>
          </div>
        ))}
        {defaults && !atDefaults && (
          <button
            type="button" className="btn btn-ghost btn-sm rp-reset"
            onClick={() => WEIGHT_FIELDS.forEach(({ key, body }) => setCostWeight(key, defaults[body]))}
          >
            <RotateCcw size={11} /> Reset to config ({defaults.w_time} · {defaults.w_fuel} · {defaults.w_risk})
          </button>
        )}
        <p className="rp-note">
          POST /route applies these to the Balanced route; the other alternatives keep their fixed
          config/routing.yaml profiles as references.
        </p>
      </div>

      <div className="rp-actions">
        <button
          type="button" className="btn btn-primary"
          onClick={() => plan()}
          disabled={isCalculating || !origin || !destination || sameEndpoints || configLoading}
        >
          {isCalculating
            ? <><Loader2 size={14} className="rp-spin" /> Calculating… {elapsed}s</>
            : <><RouteIcon size={14} /> {hasRoutes ? 'Recalculate routes' : 'Calculate routes'}</>}
        </button>
        {hasRoutes && !isCalculating && (
          <button type="button" className="btn btn-ghost btn-icon" onClick={clearRoutes} title="Clear routes" aria-label="Clear routes">
            <X size={14} />
          </button>
        )}
      </div>

      {isCalculating && (
        <p className="rp-note">Time-expanded A* across the forecast horizon — a cold run can take about a minute.</p>
      )}
      {sameEndpoints && (
        <div className="alert-card warning"><span>Origin and destination are the same.</span></div>
      )}
      {stale && !isCalculating && (
        <div className="alert-card info"><span>Inputs changed since the last calculation — recalculate to update.</span></div>
      )}
      {calculationError && (
        <div className="alert-card critical"><span>{calculationError}</span></div>
      )}
    </div>
  );
}
