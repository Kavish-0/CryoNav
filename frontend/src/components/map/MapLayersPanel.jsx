/* ═══════════════════════════════════════════════════════════════
   MapLayersPanel — projection, basemap and data-layer toggles.

   Layers with no backend data source are shown disabled rather than
   silently doing nothing, and optional layers the backend fails to serve
   say so under their toggle.
   ═══════════════════════════════════════════════════════════════ */

import React from 'react';
import { Layers, Globe } from 'lucide-react';
import { MAP_LAYERS, BASEMAPS, POLAR_BASEMAPS, POLAR_OVERLAYS } from '@utils/constants';

/* Layers with a real backend data source behind them. */
export const LIVE_LAYER_IDS = new Set([
  'icebergs', 'trajectories', 'routes', 'stations',
  'seaIce', 'seaIceForecast', 'bathymetry',
  'oceanCurrents', 'weather',
  // Joined once the backend served the router's own berg-risk field
  'riskZones',
]);

const selectStyle = { width: '100%', marginBottom: 'var(--space-3)', fontSize: 'var(--font-size-xs)' };

export default function MapLayersPanel({
  projection, onProjectionChange,
  basemapId, onBasemapChange,
  polarBasemapId, onPolarBasemapChange,
  polarOverlays, onTogglePolarOverlay,
  seaIceDate, selectedDate,
  layers, onToggleLayer, layerNotes = {},
  showLiveBergs, onToggleLiveBergs, liveBergsError,
}) {
  const isPolar = projection === 'polar';

  return (
    <div className="map-layers-panel">
      <h3><Globe size={12} /> Projection</h3>
      <select value={projection} onChange={(e) => onProjectionChange(e.target.value)} style={selectStyle}>
        <option value="polar">Polar Stereographic (EPSG:3031)</option>
        <option value="mercator">Web Mercator (EPSG:3857)</option>
      </select>

      <h3><Layers size={12} /> Basemap</h3>
      {isPolar ? (
        <select value={polarBasemapId} onChange={(e) => onPolarBasemapChange(e.target.value)} style={selectStyle}>
          {Object.entries(POLAR_BASEMAPS).map(([id, b]) => (
            <option key={id} value={id}>{b.label}</option>
          ))}
        </select>
      ) : (
        <select value={basemapId} onChange={(e) => onBasemapChange(e.target.value)} style={selectStyle}>
          {Object.entries(BASEMAPS).map(([id, b]) => (
            <option key={id} value={id}>{b.label}</option>
          ))}
        </select>
      )}

      {isPolar && (
        <>
          <h3><Layers size={12} /> NASA GIBS Overlays</h3>
          {Object.entries(POLAR_OVERLAYS).map(([id, o]) => (
            <label key={id} className={`map-layer-item ${polarOverlays[id] ? 'active' : ''}`}>
              <input type="checkbox" checked={Boolean(polarOverlays[id])} onChange={() => onTogglePolarOverlay(id)} />
              <span>{o.label}</span>
            </label>
          ))}
          {polarOverlays.seaIce && seaIceDate.clamped && (
            <p className="map-layer-note">
              Sea ice shown for {seaIceDate.date} — AMSR2 does not cover {selectedDate}.
            </p>
          )}
        </>
      )}

      <h3 style={{ marginTop: 'var(--space-3)' }}><Layers size={12} /> Data Layers</h3>
      {Object.values(MAP_LAYERS).map((layer) => {
        const live = LIVE_LAYER_IDS.has(layer.id);
        return (
          <React.Fragment key={layer.id}>
            <label
              className={`map-layer-item ${layers[layer.id] ? 'active' : ''}`}
              style={{ opacity: live ? 1 : 0.45 }}
              title={live ? undefined : 'No backend data source for this layer yet'}
            >
              <input
                type="checkbox"
                checked={Boolean(layers[layer.id])}
                disabled={!live}
                onChange={() => onToggleLayer(layer.id)}
                style={{ accentColor: layer.color }}
              />
              <span className="map-layer-color" style={{ background: layer.color }} />
              <span>{layer.label}{!live && ' (no backend)'}</span>
            </label>
            {layerNotes[layer.id] && <p className="map-layer-note">{layerNotes[layer.id]}</p>}
          </React.Fragment>
        );
      })}

      {/* Observed berg feed, kept separate from the modelled bergs so the
          distinction between measurement and prediction stays visible. */}
      <label className={`map-layer-item ${showLiveBergs ? 'active' : ''}`} title="US National Ice Center weekly bulletin">
        <input type="checkbox" checked={showLiveBergs} onChange={onToggleLiveBergs} style={{ accentColor: '#c2410c' }} />
        <span className="map-layer-color" style={{ background: '#c2410c' }} />
        <span>Icebergs (NIC observed)</span>
      </label>
      {showLiveBergs && liveBergsError && (
        <p className="map-layer-note">Live NIC feed unavailable (GET /bergs/live).</p>
      )}
    </div>
  );
}
