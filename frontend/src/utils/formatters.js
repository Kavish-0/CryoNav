/* ═══════════════════════════════════════════════════════════════
   CryoNav Formatters
   Date, coordinate, unit, and display formatting utilities
   ═══════════════════════════════════════════════════════════════ */

import { format, formatDistanceToNow, parseISO } from 'date-fns';

/* ── Date/Time ──────────────────────────────────────────────── */

/**
 * Format a date as YYYY-MM-DD
 * @param {Date|string} date
 * @returns {string}
 */
export function formatDate(date) {
  const d = typeof date === 'string' ? parseISO(date) : date;
  return format(d, 'yyyy-MM-dd');
}

/**
 * Format a date as DD MMM YYYY, HH:mm UTC
 * @param {Date|string} date
 * @returns {string}
 */
export function formatDateTime(date) {
  const d = typeof date === 'string' ? parseISO(date) : date;
  return format(d, "dd MMM yyyy, HH:mm") + ' UTC';
}

/**
 * Format as relative time (e.g. "3 hours ago")
 * @param {Date|string} date
 * @returns {string}
 */
export function formatRelativeTime(date) {
  const d = typeof date === 'string' ? parseISO(date) : date;
  return formatDistanceToNow(d, { addSuffix: true });
}

/**
 * Format as compact date for timeline labels (e.g. "Jan 20")
 * @param {Date|string} date
 * @returns {string}
 */
export function formatCompactDate(date) {
  const d = typeof date === 'string' ? parseISO(date) : date;
  return format(d, 'MMM dd');
}

/* ── Coordinates ────────────────────────────────────────────── */

/**
 * Format latitude as string with N/S suffix
 * @param {number} lat - Latitude in decimal degrees
 * @param {number} [precision=4] - Decimal places
 * @returns {string}
 */
export function formatLat(lat, precision = 4) {
  const dir = lat >= 0 ? 'N' : 'S';
  return `${Math.abs(lat).toFixed(precision)}°${dir}`;
}

/**
 * Format longitude as string with E/W suffix
 * @param {number} lon - Longitude in decimal degrees
 * @param {number} [precision=4] - Decimal places
 * @returns {string}
 */
export function formatLon(lon, precision = 4) {
  const dir = lon >= 0 ? 'E' : 'W';
  return `${Math.abs(lon).toFixed(precision)}°${dir}`;
}

/**
 * Format a lat/lon pair as a compact string
 * @param {number} lat
 * @param {number} lon
 * @returns {string}
 */
export function formatCoords(lat, lon) {
  return `${formatLat(lat, 2)}, ${formatLon(lon, 2)}`;
}

/* ── Units ──────────────────────────────────────────────────── */

/**
 * Format distance in nautical miles
 * @param {number} nm - Distance in nautical miles
 * @returns {string}
 */
export function formatDistance(nm) {
  if (nm < 1) return `${(nm * 1852).toFixed(0)} m`;
  return `${nm.toFixed(1)} nm`;
}

/**
 * Format speed in knots
 * @param {number} knots
 * @returns {string}
 */
export function formatSpeed(knots) {
  return `${knots.toFixed(1)} kn`;
}

/**
 * Format duration in hours to a readable string
 * @param {number} hours
 * @returns {string}
 */
export function formatDuration(hours) {
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours < 24) return `${hours.toFixed(1)} hrs`;
  const days = Math.floor(hours / 24);
  const remainingHours = Math.round(hours % 24);
  return `${days}d ${remainingHours}h`;
}

/**
 * Format fuel consumption in metric tons
 * @param {number} tons
 * @returns {string}
 */
export function formatFuel(tons) {
  if (tons < 1) return `${(tons * 1000).toFixed(0)} kg`;
  return `${tons.toFixed(1)} MT`;
}

/**
 * Format temperature in Celsius
 * @param {number} celsius
 * @returns {string}
 */
export function formatTemperature(celsius) {
  return `${celsius.toFixed(1)}°C`;
}

/**
 * Format wind speed
 * @param {number} ms - Speed in m/s
 * @returns {string}
 */
export function formatWindSpeed(ms) {
  return `${ms.toFixed(1)} m/s`;
}

/**
 * Format percentage
 * @param {number} value - Value 0–100
 * @param {number} [decimals=0]
 * @returns {string}
 */
export function formatPercent(value, decimals = 0) {
  return `${value.toFixed(decimals)}%`;
}

/**
 * Format a large number with k/M suffix
 * @param {number} value
 * @returns {string}
 */
export function formatCompactNumber(value) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toString();
}

/* ── Navigation ─────────────────────────────────────────────── */

/**
 * Nautical miles with thousands separators, e.g. 3049.1 → "3,049 nm"
 * @param {number} nm
 * @param {number} [decimals=0]
 * @returns {string}
 */
export function formatNauticalMiles(nm, decimals = 0) {
  if (nm === null || nm === undefined || Number.isNaN(nm)) return '—';
  return `${Number(nm).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })} nm`;
}

/**
 * Three-digit true bearing, e.g. 42.3 → "042°"
 * @param {number} degrees
 * @returns {string}
 */
export function formatBearing(degrees) {
  if (degrees === null || degrees === undefined || Number.isNaN(degrees)) return '—';
  const d = ((Math.round(degrees) % 360) + 360) % 360;
  return `${String(d).padStart(3, '0')}°`;
}

/**
 * Arrival time in UTC for a voyage departing at 00:00 UTC on `departDate`.
 * The backend routes by calendar day and has no departure time, so the
 * midnight assumption is stated wherever this is shown.
 * @param {string} departDate - YYYY-MM-DD
 * @param {number} hours - Voyage duration
 * @returns {string|null} e.g. "2023-01-22 03:00 UTC"
 */
export function formatEtaUtc(departDate, hours) {
  if (!departDate || hours === null || hours === undefined || Number.isNaN(hours)) return null;
  const t0 = Date.parse(`${departDate}T00:00:00Z`);
  if (Number.isNaN(t0)) return null;
  const iso = new Date(t0 + hours * 3600 * 1000).toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

/* ── Risk ───────────────────────────────────────────────────── */

/**
 * Get the risk level label for an ANRI value
 * @param {number} anri - ANRI 0–100
 * @returns {string}
 */
export function formatRiskLevel(anri) {
  if (anri <= 25) return 'LOW';
  if (anri <= 50) return 'MODERATE';
  if (anri <= 75) return 'HIGH';
  return 'CRITICAL';
}

/* ── Data Quality ───────────────────────────────────────────── */

/**
 * Format data quality status
 * @param {boolean} isReal
 * @returns {{ label: string, className: string }}
 */
export function formatDataQuality(isReal) {
  if (isReal === true) return { label: 'Real', className: 'real' };
  if (isReal === false) return { label: 'Synthetic', className: 'synthetic' };
  return { label: 'Unknown', className: 'unavailable' };
}
