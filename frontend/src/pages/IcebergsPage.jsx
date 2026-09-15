/* Icebergs Page — Inventory, tracking, trajectories
   Wired to GET /bergs: the largest tracked bergs for the date with their
   drift ensembles. The page reports the backend's `source` (observed
   BYU/NIC tracks or synthetic fallback) rather than assuming either. */
import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Anchor, Navigation, AlertTriangle, MapPin, ExternalLink } from 'lucide-react';
import useAppStore from '@stores/useAppStore';
import useMapStore from '@stores/useMapStore';
import { useIcebergsMeta } from '@hooks/useIcebergs';
import { describeBergSource } from '@utils/routeAssessment';
import { formatCoords } from '@utils/formatters';
import { haversineKm } from '@utils/geo';

export default function IcebergsPage() {
  const navigate = useNavigate();
  const selectedDate = useAppStore((s) => s.selectedDate);
  /* Same drift horizon as the map, and the envelope kept so the page can say
     which dataset the bergs came from instead of assuming. */
  const bergHorizon = useMapStore((s) => s.bergHorizon);
  const { data: meta, isLoading, isError, error } = useIcebergsMeta(selectedDate, bergHorizon);
  const bergs = meta?.bergs;
  const sourceInfo = describeBergSource(meta?.source);
  const [selectedBergId, setSelectedBergId] = useState(null);

  const selectedBerg = useMemo(
    () => bergs?.find((b) => b.berg_id === selectedBergId) || null,
    [bergs, selectedBergId]
  );

  const trajectoryStats = useMemo(() => {
    if (!selectedBerg) return null;
    const track = selectedBerg.mean_track; // [[day, lat, lon], ...]
    if (!track?.length) return null;
    const [, startLat, startLon] = track[0];
    const [, endLat, endLon] = track[track.length - 1];
    const driftKm = haversineKm(startLat, startLon, endLat, endLon);

    // Ensemble spread at the final day — max distance from mean final position
    let spreadKm = null;
    if (Array.isArray(selectedBerg.ensemble) && selectedBerg.ensemble.length) {
      const finalPositions = selectedBerg.ensemble.map((member) => member[member.length - 1]);
      spreadKm = Math.max(...finalPositions.map(([lat, lon]) => haversineKm(endLat, endLon, lat, lon)));
    }

    return { startLat, startLon, endLat, endLon, driftKm, spreadKm, days: track.length - 1 };
  }, [selectedBerg]);

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Iceberg Tracking</h1>
        <p className="page-subtitle">
          Tracked icebergs with ensemble drift predictions{meta?.source ? ` · source: ${meta.source}` : ''}
        </p>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-4)' }}>
        <div className="card-header">
          <div className="card-title"><Anchor size={16} /> Tracked Icebergs</div>
          {!isLoading && !isError && <span className="badge badge-cyan">{bergs?.length || 0} icebergs</span>}
        </div>
        {isError && (
          <div className="alert-card critical">
            <span>Could not load /bergs — {error?.response?.data?.detail || error?.message}</span>
          </div>
        )}
        <table className="table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Start Position ({selectedDate})</th>
              <th>Projected Position (+{bergHorizon}d)</th>
              <th>Dimensions</th>
              <th>Ensemble</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-tertiary)' }}>
                  Loading icebergs…
                </td>
              </tr>
            )}
            {!isLoading && !isError && (bergs?.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-tertiary)' }}>
                  No icebergs returned for {selectedDate}
                </td>
              </tr>
            )}
            {bergs?.map((berg) => {
              const track = berg.mean_track || [];
              const [, startLat, startLon] = track[0] || [];
              const [, endLat, endLon] = track[track.length - 1] || [];
              return (
                <tr key={berg.berg_id} style={{ background: berg.berg_id === selectedBergId ? 'var(--color-bg-tertiary)' : undefined }}>
                  <td style={{ fontWeight: 600 }}>{berg.berg_id}</td>
                  <td className="text-mono">{startLat !== undefined ? formatCoords(startLat, startLon) : '—'}</td>
                  <td className="text-mono">{endLat !== undefined ? formatCoords(endLat, endLon) : '—'}</td>
                  <td>{Math.round(berg.length_m)}m × {Math.round(berg.width_m)}m</td>
                  <td>{berg.ensemble?.length ?? 0} members</td>
                  <td>
                    <button className="btn btn-secondary btn-sm" onClick={() => setSelectedBergId(berg.berg_id)}>
                      <MapPin size={12} /> View Trajectory
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <div className="card-title"><Navigation size={16} /> Trajectory Prediction</div>
            <span className="model-tag">RK4 · Physics-Based</span>
          </div>
          {selectedBerg && trajectoryStats ? (
            <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <div className="grid-3">
                <div className="stat-card" style={{ textAlign: 'center' }}>
                  <span className="stat-value" style={{ color: 'var(--color-accent-cyan)', fontSize: 'var(--font-size-lg)' }}>
                    {trajectoryStats.driftKm.toFixed(1)}
                  </span>
                  <span className="stat-label">km net drift / {trajectoryStats.days}d</span>
                </div>
                <div className="stat-card" style={{ textAlign: 'center' }}>
                  <span className="stat-value" style={{ color: 'var(--color-accent-purple)', fontSize: 'var(--font-size-lg)' }}>
                    {trajectoryStats.spreadKm !== null ? trajectoryStats.spreadKm.toFixed(1) : '—'}
                  </span>
                  <span className="stat-label">km ensemble spread</span>
                </div>
                <div className="stat-card" style={{ textAlign: 'center' }}>
                  <span className="stat-value" style={{ color: 'var(--color-accent-blue)', fontSize: 'var(--font-size-lg)' }}>
                    {selectedBerg.ensemble?.length ?? 0}
                  </span>
                  <span className="stat-label">ensemble members</span>
                </div>
              </div>
              <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                {selectedBerg.berg_id}: {formatCoords(trajectoryStats.startLat, trajectoryStats.startLon)} → {formatCoords(trajectoryStats.endLat, trajectoryStats.endLon)} over {trajectoryStats.days} days.
                Ensemble spread is the max distance between any perturbed ensemble member's final position and the mean track's final position — a proxy for forecast uncertainty.
              </p>
              <button
                className="btn btn-secondary btn-sm"
                style={{ alignSelf: 'flex-start' }}
                onClick={() => navigate(`/trajectory?bergId=${encodeURIComponent(selectedBerg.berg_id)}&date=${encodeURIComponent(selectedDate)}`)}
              >
                <ExternalLink size={12} /> Open Full Trajectory View
              </button>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: 'var(--space-6)' }}>
              <p className="empty-state-description">
                Select an iceberg above to view its ensemble trajectory prediction.
              </p>
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title"><AlertTriangle size={16} /> Data Source &amp; Model Notes</div>
          </div>
          <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)', display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            {sourceInfo && (
              <div className={`alert-card ${sourceInfo.tone === 'success' ? 'success' : sourceInfo.tone === 'danger' ? 'critical' : 'warning'}`}>
                <span>{sourceInfo.label} (reported by GET /bergs for {selectedDate})</span>
              </div>
            )}
            <div className="alert-card info">
              <span>
                {meta?.n_ensemble ?? '—'}-member ensemble per berg over {bergHorizon} days (horizon shared with the map).
                The spread is the uncertainty — the mean track alone is not a certain position.
              </span>
            </div>
            <div className="alert-card warning">
              <span>
                Known model limitation: the drift step computes an RK4 displacement but advances position with the
                mean of the start and end velocities (src/berg/dynamics.py).
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
