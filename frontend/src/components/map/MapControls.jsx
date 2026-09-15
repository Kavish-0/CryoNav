/* ═══════════════════════════════════════════════════════════════
   MapControls — the scrubbing controls from web/app.js.

   Two things the React map was missing entirely:

     · Lead-day slider (1–14) with a play button that steps through the
       forecast horizon. This is how you actually see the ice advance.
     · SIC display mode — observed, forecast, or the difference between
       them. The difference view is the honest one: it shows where the
       model is wrong, not just what it predicted.

   Also a berg horizon slider, since drift and forecast horizons are
   separate questions.
   ═══════════════════════════════════════════════════════════════ */

import React, { useEffect, useRef } from 'react';
import { Play, Pause, Layers as LayersIcon } from 'lucide-react';
import { BERG_HORIZON_PRESETS } from '@utils/constants';

export const SIC_MODES = [
  { id: 'observed', label: 'Observed' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'difference', label: 'Difference' },
];

const ANIMATION_MS = 650;

export default function MapControls({
  leadDay, setLeadDay,
  bergHorizon, setBergHorizon,
  sicMode, setSicMode,
  playing, setPlaying,
  validDate, forecastSource,
}) {
  const timer = useRef(null);

  /* Lead-day animation. Steps 1→14 then stops, rather than looping
     forever and pulling fields nobody is watching. */
  useEffect(() => {
    if (!playing) {
      if (timer.current) { clearInterval(timer.current); timer.current = null; }
      return undefined;
    }
    timer.current = setInterval(() => {
      setLeadDay((d) => {
        if (d >= 14) { setPlaying(false); return 14; }
        return d + 1;
      });
    }, ANIMATION_MS);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [playing, setLeadDay, setPlaying]);

  const showLead = sicMode !== 'observed';

  return (
    <div className="map-controls">
      <div className="mc-head">
        <LayersIcon size={12} />
        <span>Sea Ice</span>
      </div>

      {/* Display mode */}
      <div className="mc-modes">
        {SIC_MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            className={`mc-mode ${sicMode === m.id ? 'is-active' : ''}`}
            onClick={() => setSicMode(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      {sicMode === 'difference' && (
        <div className="mc-legend">
          <span className="mc-legend-swatch mc-neg" /> under
          <span className="mc-legend-swatch mc-pos" /> over
          <span className="mc-legend-note">forecast − observed</span>
        </div>
      )}

      {/* Lead day */}
      {showLead && (
        <div className="mc-block">
          <div className="mc-row">
            <span className="mc-label">Lead day</span>
            <span className="mc-value">+{leadDay}d</span>
            <button
              type="button"
              className="mc-play"
              onClick={() => setPlaying(!playing)}
              title={playing ? 'Pause' : 'Animate 1 → 14 days'}
            >
              {playing ? <Pause size={12} /> : <Play size={12} />}
            </button>
          </div>
          <input
            type="range" min={1} max={14} step={1} value={leadDay}
            onChange={(e) => { setPlaying(false); setLeadDay(Number(e.target.value)); }}
          />
          {validDate && (
            <div className="mc-note">
              Valid {validDate}
              {forecastSource === 'observed_fallback' && ' · observed fallback'}
            </div>
          )}
        </div>
      )}

      {/* Berg horizon */}
      <div className="mc-block">
        <div className="mc-row">
          <span className="mc-label">Berg drift</span>
          <span className="mc-value">+{bergHorizon}d</span>
        </div>
        {/* Main's client allows drift out to 60 days; the 14-day cap here
            was the forecast horizon, which is a different question. */}
        <input
          type="range" min={1} max={60} step={1} value={bergHorizon}
          onChange={(e) => setBergHorizon(Number(e.target.value))}
        />
        <div className="mc-modes mc-presets" aria-label="Drift horizon presets">
          {BERG_HORIZON_PRESETS.map((days) => (
            <button
              key={days}
              type="button"
              className={`mc-mode ${bergHorizon === days ? 'is-active' : ''}`}
              onClick={() => setBergHorizon(days)}
            >
              {days}d
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
