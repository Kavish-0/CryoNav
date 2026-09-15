/* ═══════════════════════════════════════════════════════════════
   Route geometry → navigation indications and hazard screening.

   Everything here is derived in the browser from data the backend already
   returns: the route polyline (POST /route `path_latlon`), the sea-ice
   field (GET /observed + GET /grid) and the iceberg drift ensembles
   (GET /bergs). The backend returns no waypoints or headings of its own,
   so these are decision-support indications for understanding and
   comparing routes — not certified navigational guidance.
   ═══════════════════════════════════════════════════════════════ */

import {
  haversineNm, haversineKm, initialBearing, finalBearing, compassPoint,
  signedAngleDelta, unwrapLongitudes, normalizeLon, toPolarPlane,
  distanceToPathNm, METRES_PER_NM,
} from './geo';
import { BERG_PROXIMITY_NM, SIC_ROUTE_BANDS } from './constants';

/* ── Path preparation ───────────────────────────────────────── */

/** Valid points only, longitudes unwrapped, near-duplicates dropped, with along-track distance. */
function preparePath(path) {
  const valid = (path || []).filter(
    (p) => Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1])
  );
  const points = [];
  const cumulative = [];
  for (const p of unwrapLongitudes(valid)) {
    if (points.length) {
      const prev = points[points.length - 1];
      const d = haversineNm(prev[0], prev[1], p[0], p[1]);
      if (d < 0.05) continue;
      cumulative.push(cumulative[cumulative.length - 1] + d);
    } else {
      cumulative.push(0);
    }
    points.push(p);
  }
  return { points, cumulative, totalNm: cumulative.length ? cumulative[cumulative.length - 1] : 0 };
}

/** Douglas–Peucker on a planar polyline. Returns the indices that survive. */
function simplifyIndices(plane, tolerance) {
  const n = plane.length;
  if (n <= 2) return plane.map((_, i) => i);

  const keep = new Uint8Array(n);
  keep[0] = 1;
  keep[n - 1] = 1;
  const stack = [[0, n - 1]];

  while (stack.length) {
    const [s, e] = stack.pop();
    const [ax, ay] = plane[s];
    const [bx, by] = plane[e];
    const dx = bx - ax;
    const dy = by - ay;
    const len = Math.hypot(dx, dy);

    let maxD = -1;
    let idx = -1;
    for (let i = s + 1; i < e; i += 1) {
      const [px, py] = plane[i];
      const d = len > 0
        ? Math.abs(dy * px - dx * py + bx * ay - by * ax) / len
        : Math.hypot(px - ax, py - ay);
      if (d > maxD) { maxD = d; idx = i; }
    }
    if (idx !== -1 && maxD > tolerance) {
      keep[idx] = 1;
      stack.push([s, idx], [idx, e]);
    }
  }

  const out = [];
  for (let i = 0; i < n; i += 1) if (keep[i]) out.push(i);
  return out;
}

/** Remove interior vertices that would leave a leg shorter than `minLegNm`. */
function dropShortLegs(indices, cumulative, minLegNm) {
  const idx = [...indices];
  let changed = true;
  while (changed && idx.length > 2) {
    changed = false;
    for (let k = 1; k < idx.length - 1; k += 1) {
      const before = cumulative[idx[k]] - cumulative[idx[k - 1]];
      const after = cumulative[idx[k + 1]] - cumulative[idx[k]];
      if (before < minLegNm || after < minLegNm) {
        idx.splice(k, 1);
        changed = true;
        break;
      }
    }
  }
  return idx;
}

/* ── Route legs ─────────────────────────────────────────────── */

/**
 * Break a route polyline into straight-ish legs.
 *
 * The path is simplified (Douglas–Peucker, in the polar plane) until it has
 * at most `maxLegs` legs; the tolerance used is returned so the UI can say
 * how far the legs may depart from the plotted route. Leg distances are
 * measured along the ORIGINAL path, not the simplified chord.
 *
 * @param {number[][]} path - [[lat, lon], ...]
 * @returns {{points, cumulative, totalNm, toleranceNm, legs: Array<{
 *   index, start:{lat,lon}, end:{lat,lon}, bearing, compass, turnDeg,
 *   distanceNm, startNm, endNm, positions
 * }>}}
 */
export function buildRouteGeometry(path, { maxLegs = 24, minToleranceNm = 4, minLegNm = 3 } = {}) {
  const { points, cumulative, totalNm } = preparePath(path);
  if (points.length < 2) return { points, cumulative, totalNm, toleranceNm: 0, legs: [] };

  const plane = points.map(([lat, lon]) => toPolarPlane(lat, lon));
  let toleranceNm = minToleranceNm;
  let indices = simplifyIndices(plane, toleranceNm);
  for (let i = 0; i < 12 && indices.length - 1 > maxLegs; i += 1) {
    toleranceNm *= 1.5;
    indices = simplifyIndices(plane, toleranceNm);
  }
  indices = dropShortLegs(indices, cumulative, minLegNm);

  const legs = [];
  let previousFinal = null;
  for (let k = 1; k < indices.length; k += 1) {
    const s = indices[k - 1];
    const e = indices[k];
    const [lat1, lon1] = points[s];
    const [lat2, lon2] = points[e];
    const bearing = initialBearing(lat1, lon1, lat2, lon2);

    legs.push({
      index: k,
      startIndex: s,
      endIndex: e,
      start: { lat: lat1, lon: normalizeLon(lon1) },
      end: { lat: lat2, lon: normalizeLon(lon2) },
      bearing,
      compass: compassPoint(bearing),
      // Course alteration at the start of this leg, relative to how the previous leg ended
      turnDeg: previousFinal === null ? null : signedAngleDelta(previousFinal, bearing),
      distanceNm: cumulative[e] - cumulative[s],
      startNm: cumulative[s],
      endNm: cumulative[e],
      positions: points.slice(s, e + 1),
    });
    previousFinal = finalBearing(lat1, lon1, lat2, lon2);
  }

  return { points, cumulative, totalNm, toleranceNm, legs };
}

const geometryCache = new WeakMap();

/** Route geometry for a normalized route, computed once per route object and shared by every view. */
export function getRouteGeometry(route) {
  if (!route?.success || !route.path?.length) return null;
  let geometry = geometryCache.get(route);
  if (!geometry) {
    geometry = buildRouteGeometry(route.path);
    geometryCache.set(route, geometry);
  }
  return geometry;
}

/** Interpolated position at an along-track distance (nm) from departure. */
export function pointAtDistance(geometry, distanceNm) {
  const { points, cumulative, totalNm } = geometry;
  if (!points.length) return null;
  const d = Math.max(0, Math.min(distanceNm, totalNm));

  let lo = 0;
  let hi = cumulative.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (cumulative[mid] <= d) lo = mid; else hi = mid;
  }
  const span = cumulative[hi] - cumulative[lo];
  const t = span > 0 ? (d - cumulative[lo]) / span : 0;
  return {
    lat: points[lo][0] + (points[hi][0] - points[lo][0]) * t,
    lon: points[lo][1] + (points[hi][1] - points[lo][1]) * t,
    index: lo,
  };
}

/* ── Iceberg drift helpers ──────────────────────────────────── */

/** Displacement in km between two positions (great circle). */
export function displacementKm(lat0, lon0, lat1, lon1) {
  return haversineKm(lat0, lon0, lat1, lon1);
}

/**
 * 2σ ensemble spread at the final drift step, as a circle in metres.
 * Returns null when there aren't enough members to say anything.
 */
export function ensembleSpread(ensemble) {
  if (!ensemble || ensemble.length < 3) return null;
  const lastIdx = ensemble[0].length - 1;
  const lats = ensemble.map((e) => e[lastIdx]?.[0]).filter((v) => typeof v === 'number');
  const lons = ensemble.map((e) => e[lastIdx]?.[1]).filter((v) => typeof v === 'number');
  if (lats.length < 3) return null;

  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
  const meanLat = mean(lats);
  const meanLon = mean(lons);
  const std = (a, m) => Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / a.length);

  const radiusLat = std(lats, meanLat) * 2 * 111320;
  const radiusLon = std(lons, meanLon) * 2 * 111320 * Math.cos((meanLat * Math.PI) / 180);
  // Floor at 6 km so a tight ensemble is still visible at low zoom
  return { lat: meanLat, lon: meanLon, radius: Math.max(radiusLat, radiusLon, 6000) };
}

/** Mean-track position at an hour after the drift start, or null beyond the drift horizon. */
function bergPositionAtHour(track, hour) {
  const day = hour / 24;
  if (day <= track[0][0]) return { lat: track[0][1], lon: track[0][2] };
  for (let i = 1; i < track.length; i += 1) {
    const [d0, lat0, lon0] = track[i - 1];
    const [d1, lat1, lon1] = track[i];
    if (day <= d1) {
      const t = (day - d0) / (d1 - d0 || 1);
      const dLon = ((((lon1 - lon0) + 540) % 360) + 360) % 360 - 180;
      return { lat: lat0 + (lat1 - lat0) * t, lon: lon0 + dLon * t };
    }
  }
  return null;
}

const LEVEL_ORDER = { danger: 0, caution: 1, clear: 2 };

/**
 * Screen each drifting berg against a route.
 *
 *   closest    — nearest ship-to-berg separation at the same moment, with the
 *                ship assumed to cover the route at uniform speed over the
 *                backend's time_h, less half the berg's length
 *   minTrackNm — nearest the berg's mean drift track comes to the route at
 *                any time (timing ignored)
 *   envelope   — the 2σ ensemble circle at the end of the drift horizon, and
 *                how far its edge is from the route (≤ 0 = route crosses it)
 *
 * Levels use BERG_PROXIMITY_NM. This is a geometric screen of the same bergs
 * the router considered, not the backend's own berg-risk field.
 */
export function assessBergProximity(bergs, geometry, voyageHours, { stepHours = 2 } = {}) {
  if (!geometry?.points?.length || !bergs?.length) return [];
  const { points, totalNm } = geometry;

  return bergs
    .filter((b) => b.mean_track?.length)
    .map((berg) => {
      const track = berg.mean_track;
      const halfLengthNm = (berg.length_m || 0) / 2 / METRES_PER_NM;

      let minTrackNm = Infinity;
      let minTrackDay = null;
      for (const [day, lat, lon] of track) {
        const { nm } = distanceToPathNm(lat, lon, points);
        if (nm < minTrackNm) { minTrackNm = nm; minTrackDay = day; }
      }

      const horizonHours = track[track.length - 1][0] * 24;
      let closest = null;
      if (voyageHours > 0 && totalNm > 0) {
        const end = Math.min(voyageHours, horizonHours);
        for (let h = 0; h <= end; h += stepHours) {
          const ship = pointAtDistance(geometry, totalNm * (h / voyageHours));
          const pos = bergPositionAtHour(track, h);
          if (!ship || !pos) continue;
          const nm = haversineNm(ship.lat, ship.lon, pos.lat, pos.lon);
          if (!closest || nm < closest.nm) {
            closest = { nm, clearanceNm: Math.max(0, nm - halfLengthNm), hour: h };
          }
        }
      }

      const spread = ensembleSpread(berg.ensemble);
      const envelope = spread
        ? {
          lat: spread.lat,
          lon: spread.lon,
          radiusNm: spread.radius / METRES_PER_NM,
          edgeNm: distanceToPathNm(spread.lat, spread.lon, points).nm - spread.radius / METRES_PER_NM,
          day: track[track.length - 1][0],
        }
        : null;

      let level = 'clear';
      if ((closest && closest.clearanceNm <= BERG_PROXIMITY_NM.danger) || (envelope && envelope.edgeNm <= 0)) {
        level = 'danger';
      } else if (
        minTrackNm - halfLengthNm <= BERG_PROXIMITY_NM.caution
        || (envelope && envelope.edgeNm <= BERG_PROXIMITY_NM.caution)
      ) {
        level = 'caution';
      }

      return {
        bergId: berg.berg_id,
        lengthM: berg.length_m,
        level,
        closest,
        minTrackNm,
        minTrackDay,
        envelope,
        horizonDays: track[track.length - 1][0],
        coversVoyage: voyageHours <= horizonHours,
      };
    })
    .sort((a, b) =>
      LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level]
      || (a.closest?.clearanceNm ?? a.minTrackNm) - (b.closest?.clearanceNm ?? b.minTrackNm));
}

/* ── Sea ice along a route ──────────────────────────────────── */

const locatorCache = new WeakMap();
const BIN_LAT = 0.5;
const BIN_LON = 1.5;
const LON_BINS = Math.round(360 / BIN_LON);

/**
 * Nearest-cell lookup for the curvilinear model grid (GET /grid), using a
 * coarse lat/lon bin index so a lookup touches a few dozen cells instead of
 * all of them. Built once per grid object.
 */
export function createGridLocator(grid) {
  if (!grid?.lat || !grid?.lon) return null;
  const cached = locatorCache.get(grid);
  if (cached) return cached;

  const ny = grid.lat.length;
  const nx = grid.lat[0]?.length ?? 0;
  const bins = new Map();
  const lonBin = (lon) => {
    const b = Math.floor((normalizeLon(lon) + 180) / BIN_LON);
    return ((b % LON_BINS) + LON_BINS) % LON_BINS;
  };

  for (let y = 0; y < ny; y += 1) {
    for (let x = 0; x < nx; x += 1) {
      const lat = grid.lat[y][x];
      const lon = grid.lon[y][x];
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      const key = `${Math.floor(lat / BIN_LAT)}:${lonBin(lon)}`;
      let list = bins.get(key);
      if (!list) { list = []; bins.set(key, list); }
      list.push(y * nx + x);
    }
  }

  const locator = {
    shape: [ny, nx],
    /** Nearest grid cell within `maxKm`, or null outside the grid. */
    nearest(lat, lon, maxKm = 30) {
      const by = Math.floor(lat / BIN_LAT);
      const bx = lonBin(lon);
      let best = null;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const list = bins.get(`${by + dy}:${(bx + dx + LON_BINS) % LON_BINS}`);
          if (!list) continue;
          for (const i of list) {
            const y = Math.floor(i / nx);
            const x = i % nx;
            const km = haversineKm(lat, lon, grid.lat[y][x], grid.lon[y][x]);
            if (!best || km < best.km) best = { y, x, km };
          }
        }
      }
      return best && best.km <= maxKm ? best : null;
    },
  };
  locatorCache.set(grid, locator);
  return locator;
}

/** Band id for a concentration, from SIC_ROUTE_BANDS (sorted high → low). */
export function sicBandOf(value) {
  if (value === null || value === undefined) return null;
  return SIC_ROUTE_BANDS.find((b) => value >= b.min)?.id ?? null;
}

/**
 * Sample a sea-ice field along a route every ~`stepNm`.
 *
 * Each stretch between two samples takes the higher of its two values, so
 * ice is never under-reported between samples. Stretches outside the model
 * grid (open-ocean lead-in from a port, say) are excluded from coverage.
 *
 * @returns {{segments, bandNm, coveredNm, totalNm, max, stepNm}|null}
 */
export function sampleSicAlongRoute(geometry, locator, sic, landMask, { stepNm = 10 } = {}) {
  if (!geometry?.points?.length || !locator || !sic) return null;

  const n = Math.max(1, Math.ceil(geometry.totalNm / stepNm));
  const samples = [];
  for (let i = 0; i <= n; i += 1) {
    const d = (geometry.totalNm * i) / n;
    const p = pointAtDistance(geometry, d);
    const cell = locator.nearest(p.lat, p.lon);
    let value = null;
    if (cell && !(landMask?.[cell.y]?.[cell.x] > 0.5)) {
      const v = sic[cell.y]?.[cell.x];
      if (Number.isFinite(v)) value = Math.max(0, Math.min(1, v));
    }
    samples.push({ d, lat: p.lat, lon: p.lon, value });
  }

  const bandNm = Object.fromEntries(SIC_ROUTE_BANDS.map((b) => [b.id, 0]));
  const segments = [];
  let coveredNm = 0;
  let max = null;
  let current = null;

  for (let i = 1; i < samples.length; i += 1) {
    const a = samples[i - 1];
    const b = samples[i];
    const len = b.d - a.d;
    const value = a.value === null ? b.value : b.value === null ? a.value : Math.max(a.value, b.value);
    const band = sicBandOf(value);

    if (band) {
      coveredNm += len;
      bandNm[band] += len;
      if (!max || value > max.value) {
        const at = (b.value ?? -1) >= (a.value ?? -1) ? b : a;
        max = { value, atNm: at.d, lat: at.lat, lon: normalizeLon(at.lon) };
      }
    }

    if (!current || current.band !== band) {
      current = { band, fromNm: a.d, toNm: b.d, peak: value, positions: [[a.lat, a.lon], [b.lat, b.lon]] };
      segments.push(current);
    } else {
      current.toNm = b.d;
      current.peak = Math.max(current.peak ?? 0, value ?? 0);
      current.positions.push([b.lat, b.lon]);
    }
  }

  return {
    segments: segments.filter((s) => s.band),
    bandNm,
    coveredNm,
    totalNm: geometry.totalNm,
    max,
    stepNm: geometry.totalNm / n,
  };
}
