/* ═══════════════════════════════════════════════════════════════
   Route assessment — labels for backend route numbers.

   POST /route returns raw values (hours in ice, peak berg-presence
   probability, which forecast and berg dataset it used). These helpers
   turn them into the Low / Moderate / High and source labels the UI shows,
   using the thresholds in constants.js so every view agrees.
   ═══════════════════════════════════════════════════════════════ */

import { BERG_RISK_BANDS, ICE_EXPOSURE_BANDS } from './constants';

export const RISK_LEVEL_LABELS = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  unknown: 'Unknown',
};

/** Band for `max_berg_risk` (peak berg-presence probability along the route, 0–1). */
export function bergRiskLevel(maxBergRisk) {
  if (maxBergRisk === null || maxBergRisk === undefined || Number.isNaN(maxBergRisk)) return 'unknown';
  if (maxBergRisk >= BERG_RISK_BANDS.high) return 'high';
  if (maxBergRisk >= BERG_RISK_BANDS.moderate) return 'moderate';
  return 'low';
}

/** Band for sea-ice exposure from hours spent in SIC > 30% and SIC > 70%. */
export function iceExposureLevel(iceHours03, iceHours07) {
  if (iceHours03 == null && iceHours07 == null) return 'unknown';
  if ((iceHours07 ?? 0) >= ICE_EXPOSURE_BANDS.highHours07) return 'high';
  if ((iceHours07 ?? 0) > 0 || (iceHours03 ?? 0) >= ICE_EXPOSURE_BANDS.moderateHours03) return 'moderate';
  return 'low';
}

/** Proximity screen levels (utils/navigation.assessBergProximity) mapped onto risk styling. */
export const PROXIMITY_LEVELS = {
  danger: { risk: 'high', label: 'Danger' },
  caution: { risk: 'moderate', label: 'Caution' },
  clear: { risk: 'low', label: 'Clear' },
};

/** What the router's `forecast_source` means for the user. */
export function describeForecastSource(source) {
  if (source === 'model') return { label: 'Routed on U-Net sea-ice forecast', tone: 'success' };
  if (source === 'observed_fallback') {
    return { label: 'No cached forecast for this date — routed on observed ice', tone: 'warning' };
  }
  if (!source) return null;
  return { label: `Sea-ice source: ${source}`, tone: 'blue' };
}

/** What the router's / GET /bergs `source` means for the user. */
export function describeBergSource(source) {
  if (source === 'observed') return { label: 'Icebergs: observed BYU/NIC tracks', tone: 'success' };
  if (source === 'synthetic') return { label: 'Icebergs: SYNTHETIC positions (demo data, not observations)', tone: 'warning' };
  if (source === 'unavailable') return { label: 'Iceberg risk unavailable — not included in routing', tone: 'danger' };
  if (!source) return null;
  return { label: `Iceberg source: ${source}`, tone: 'blue' };
}
