/* ═══════════════════════════════════════════════════════════════
   CryoNav Geo Utilities

   Spherical geometry for routes and icebergs. Nautical-mile distances use
   the same Earth radius as the backend router (3440.065 nm), so values
   derived here line up with the numbers POST /route reports.
   ═══════════════════════════════════════════════════════════════ */

const EARTH_RADIUS_KM = 6371;
export const EARTH_RADIUS_NM = 3440.065;
export const METRES_PER_NM = 1852;

const toRad = (d) => (d * Math.PI) / 180;
const toDeg = (r) => (r * 180) / Math.PI;

/** Wrap a longitude difference into [-180, 180). */
const wrapDelta = (d) => ((((d + 540) % 360) + 360) % 360) - 180;

/**
 * Great-circle distance between two lat/lon points (km).
 */
export function haversineKm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(a));
}

/** Great-circle distance between two lat/lon points (nautical miles). */
export function haversineNm(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Longitude folded into [-180, 180). */
export function normalizeLon(lon) {
  return wrapDelta(lon);
}

/** Initial great-circle bearing from point 1 towards point 2, degrees true (0–360). */
export function initialBearing(lat1, lon1, lat2, lon2) {
  const p1 = toRad(lat1);
  const p2 = toRad(lat2);
  const dl = toRad(lon2 - lon1);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (toDeg(Math.atan2(y, x)) + 360) % 360;
}

/** Bearing on arrival at point 2 when following the great circle from point 1. */
export function finalBearing(lat1, lon1, lat2, lon2) {
  return (initialBearing(lat2, lon2, lat1, lon1) + 180) % 360;
}

const COMPASS_16 = [
  'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
];

/** 16-point compass name for a bearing, e.g. 42° → "NE". */
export function compassPoint(bearing) {
  const b = ((bearing % 360) + 360) % 360;
  return COMPASS_16[Math.round(b / 22.5) % 16];
}

/** Signed change from one bearing to another, in (-180, 180]. Positive = clockwise (starboard). */
export function signedAngleDelta(from, to) {
  const d = wrapDelta(to - from);
  return d === -180 ? 180 : d;
}

/**
 * Keep consecutive longitudes within 180° of each other, so a line that
 * crosses the antimeridian is drawn the short way instead of across the map.
 */
export function unwrapLongitudes(path) {
  if (!path?.length) return [];
  const out = [[path[0][0], path[0][1]]];
  let prev = path[0][1];
  for (let i = 1; i < path.length; i += 1) {
    const lon = prev + wrapDelta(path[i][1] - prev);
    out.push([path[i][0], lon]);
    prev = lon;
  }
  return out;
}

/**
 * South polar stereographic plane, in nautical miles, with the pole at the
 * origin. Conformal and continuous across the antimeridian, which makes it
 * the right plane for simplifying a Southern Ocean route. Scale error is
 * ~3% at 70°S and ~28% at 34°S, so it is used for shape decisions only —
 * reported distances always come from haversineNm.
 */
export function toPolarPlane(lat, lon) {
  const rho = 2 * EARTH_RADIUS_NM * Math.tan(Math.PI / 4 + toRad(lat) / 2);
  const l = toRad(lon);
  return [rho * Math.sin(l), -rho * Math.cos(l)];
}

/**
 * Shortest distance (nm) from a point to a polyline of [lat, lon] pairs,
 * with the nearest segment index and the fraction along it.
 *
 * Each segment is measured in a local equirectangular plane centred on the
 * query point. For the short segments POST /route returns that is accurate
 * to well under 1%, and it is unaffected by the antimeridian.
 */
export function distanceToPathNm(lat, lon, path) {
  const best = { nm: Infinity, index: -1, t: 0 };
  if (!path?.length) return best;

  const k = Math.cos(toRad(lat));
  const local = (p) => [wrapDelta(p[1] - lon) * k * 60, (p[0] - lat) * 60];

  let [ax, ay] = local(path[0]);
  if (path.length === 1) return { nm: Math.hypot(ax, ay), index: 0, t: 0 };

  for (let i = 1; i < path.length; i += 1) {
    const [bx, by] = local(path[i]);
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
    const nm = Math.hypot(ax + t * dx, ay + t * dy);
    if (nm < best.nm) {
      best.nm = nm;
      best.index = i - 1;
      best.t = t;
    }
    ax = bx;
    ay = by;
  }
  return best;
}
