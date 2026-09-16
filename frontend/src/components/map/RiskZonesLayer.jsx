/* ═══════════════════════════════════════════════════════════════
   RiskZonesLayer — the router's own iceberg-risk field (GET /risk-field).

   This is not a re-derivation in the browser: it is the same probability
   field POST /route costs its paths against, so what the map shades is what
   the router avoided. Drawn with the existing SIC canvas layer, which
   already handles the curvilinear grid, viewport culling and repaint
   scheduling — only the colour ramp differs.
   ═══════════════════════════════════════════════════════════════ */

import React from 'react';
import SicCanvasLayer from './SicCanvasLayer';

/**
 * Berg-presence probability ramp: amber where the ensemble sometimes reaches,
 * red where most members do. Below 5% nothing is drawn, so open water stays
 * readable.
 */
export function bergRiskColor(value) {
  if (value <= 0.05) return null;
  if (value < 0.2) {
    const t = (value - 0.05) / 0.15;
    return `rgba(217, 119, 6, ${0.18 + t * 0.22})`;
  }
  if (value < 0.5) {
    const t = (value - 0.2) / 0.3;
    return `rgba(${Math.round(217 - t * 19)}, ${Math.round(119 - t * 79)}, ${Math.round(6 + t * 34)}, ${0.40 + t * 0.18})`;
  }
  const t = Math.min(1, (value - 0.5) / 0.5);
  return `rgba(198, 40, 40, ${0.58 + t * 0.22})`;
}

export default function RiskZonesLayer({ risk, grid }) {
  if (!risk || !grid) return null;
  return <SicCanvasLayer sic={risk} grid={grid} colorFn={bergRiskColor} />;
}
