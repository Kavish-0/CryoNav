/* ═══════════════════════════════════════════════════════════════
   Route Service — POST /route
   Aligned to Arman0212/CryoNav src/api/main.py

   The backend's RouteRequest body is FLAT:
     { origin, destination, depart_date, w_time, w_fuel, w_risk, berg_limit }

   A single POST /route call computes every alternative profile defined in
   config/routing.yaml (great_circle, min_ice, min_time, balanced,
   persistence_route) plus a comparison table and an assessment of each —
   there is no separate "optimize" endpoint or per-route detail endpoint.

   w_time / w_fuel / w_risk are applied to the "balanced" profile
   (generate_alternatives' weight_overrides); the other profiles keep their
   configured weights so they remain fixed references.
   ═══════════════════════════════════════════════════════════════ */

import apiClient from './api';
import {
  ROUTE_PROFILES, ROUTE_PROFILE_ORDER, RECOMMENDED_PROFILE, FALLBACK_ROUTE_STYLE,
} from '@utils/constants';

const rank = (key) => {
  const i = ROUTE_PROFILE_ORDER.indexOf(key);
  return i === -1 ? ROUTE_PROFILE_ORDER.length : i;
};

/**
 * Add a display-ready `list` of alternatives to a POST /route response.
 *
 * The raw response is kept intact (other views read `comparison` and
 * `origin` directly). Each list entry carries the backend's numbers under
 * camelCase names, the backend's own assessment text, and the letter,
 * colour and line style every view uses to refer to that alternative.
 *
 * @param {Object} data - Raw POST /route response
 * @returns {Object} The response plus `list`
 */
export function normalizeRouteResult(data) {
  if (!data?.routes) return data;

  const assessments = new Map(
    (data.comparison?.rejections || []).filter((r) => r.key).map((r) => [r.key, r])
  );
  const backendRecommends = [...assessments.values()].some((r) => r.recommended);
  let nextLetter = 'A'.charCodeAt(0) + ROUTE_PROFILE_ORDER.length;

  const list = Object.keys(data.routes)
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((key) => {
      const r = data.routes[key];
      const meta = ROUTE_PROFILES[key];
      const assessment = assessments.get(key);
      return {
        key,
        letter: meta?.letter ?? String.fromCharCode(nextLetter++),
        label: meta?.label ?? r.profile_name ?? key,
        profileName: r.profile_name ?? key,
        summary: meta?.summary ?? FALLBACK_ROUTE_STYLE.summary,
        color: meta?.color ?? FALLBACK_ROUTE_STYLE.color,
        dashArray: meta ? meta.dashArray : FALLBACK_ROUTE_STYLE.dashArray,
        recommended: backendRecommends ? Boolean(assessment?.recommended) : key === RECOMMENDED_PROFILE,
        success: Boolean(r.success),
        path: Array.isArray(r.path_latlon) ? r.path_latlon : [],
        distanceNm: r.distance_nm ?? null,
        timeH: r.time_h ?? null,
        fuelT: r.fuel_t ?? null,
        iceHours03: r.ice_hours_03 ?? null,
        iceHours07: r.ice_hours_07 ?? null,
        maxBergRisk: r.max_berg_risk ?? null,
        assessment: assessment?.reason ?? null,
      };
    });

  return { ...data, list };
}

const routeService = {
  /**
   * Compute routes between an origin and destination.
   *
   * @param {Object} params
   * @param {string} [params.origin='cape_town'] - Origin id (must be a key in DOMAIN.origins or DOMAIN.stations)
   * @param {string} [params.destination='bharati'] - Destination id (must be a key in DOMAIN.stations or DOMAIN.origins)
   * @param {string} [params.departDate='2023-01-13'] - Departure date (YYYY-MM-DD)
   * @param {number} [params.wTime=1.0] - Time cost weight (balanced profile)
   * @param {number} [params.wFuel=0.5] - Fuel cost weight (balanced profile)
   * @param {number} [params.wRisk=2.0] - Risk cost weight (balanced profile)
   * @param {number} [params.bergLimit=8] - How many of the largest bergs feed the risk field
   * @returns {Promise<Object>} Normalized response — see normalizeRouteResult
   */
  async calculateRoute({
    origin = 'cape_town',
    destination = 'bharati',
    departDate = '2023-01-13',
    wTime = 1.0,
    wFuel = 0.5,
    wRisk = 2.0,
    bergLimit = 8,
  } = {}) {
    /* The A* search runs synchronously over the data cube. On a departure
       date with no cached forecast it measures ~55 s cold, which blows past
       apiClient's 30 s default and surfaces as a spurious "Request timed
       out". Only this endpoint is slow, so widen it here rather than
       globally. Silent: the planner shows failures inline. */
    const { data } = await apiClient.post('/route', {
      origin,
      destination,
      depart_date: departDate,
      w_time: wTime,
      w_fuel: wFuel,
      w_risk: wRisk,
      berg_limit: bergLimit,
    }, { timeout: 180000, silent: true });
    return normalizeRouteResult(data);
  },

  /**
   * Kept for backward compatibility with call sites expecting "optimize
   * across multiple objectives" — the backend already returns every
   * alternative profile from a single POST /route call, so this is an alias.
   */
  async optimizeRoutes(params) {
    return this.calculateRoute(params);
  },

  /**
   * Pick one alternative profile out of an already-fetched /route
   * response — there is no GET /routes/{id}/profile endpoint server-side.
   *
   * @param {Object} routeResponse - The object returned by calculateRoute()
   * @param {string} profileKey - e.g. 'balanced', 'min_ice', 'min_time', 'great_circle', 'persistence_route'
   * @returns {Object|undefined} The normalized list entry
   */
  getRouteProfile(routeResponse, profileKey) {
    return routeResponse?.list?.find((r) => r.key === profileKey);
  },
};

export default routeService;
