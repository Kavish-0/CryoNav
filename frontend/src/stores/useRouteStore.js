/* ═══════════════════════════════════════════════════════════════
   useRouteStore — Route planning, alternatives and the selected route

   The selected route lives here rather than in any one component, so the
   map, the route cards, the Routes page and the dashboard all agree on
   which alternative the user is looking at.
   ═══════════════════════════════════════════════════════════════ */

import { create } from 'zustand';
import { RECOMMENDED_PROFILE } from '@utils/constants';

/**
 * Which alternative to select after a calculation: the planner's priority
 * if it succeeded, else the backend's recommended route, else the first
 * route that found a path.
 */
function pickDefaultRoute(result, preferred) {
  const list = result?.list || [];
  const ok = (key) => list.find((r) => r.key === key && r.success);
  return (ok(preferred) || ok(RECOMMENDED_PROFILE) || list.find((r) => r.success))?.key ?? null;
}

const useRouteStore = create((set) => ({
  /* ── Route Planning ── */
  origin: null,       // { id, name, lat, lon } or null
  destination: null,  // { id, name, lat, lon } or null
  setOrigin: (origin) => set({ origin }),
  setDestination: (destination) => set({ destination }),
  swapEndpoints: () => set((s) => ({ origin: s.destination, destination: s.origin })),

  /* ── Planner Preferences ──
     Both are real inputs. `bergLimit` is POST /route's berg_limit — how many
     of the largest bergs feed the router's risk field. `preferredProfile`
     decides which of the computed alternatives gets selected. */
  preferredProfile: RECOMMENDED_PROFILE,
  setPreferredProfile: (preferredProfile) =>
    set((s) => {
      const available = s.routes?.list?.some((r) => r.key === preferredProfile && r.success);
      return available
        ? { preferredProfile, selectedRouteId: preferredProfile, focusedLegIndex: null }
        : { preferredProfile };
    }),
  bergLimit: 8,
  setBergLimit: (bergLimit) => set({ bergLimit }),

  /* ── Cost Weights ──
     Matches POST /route's { w_time, w_fuel, w_risk }. The backend applies
     them to the "balanced" profile only; the other alternatives keep their
     configured weights as fixed references. Defaults match
     config/routing.yaml cost_weights. */
  costWeights: {
    wTime: 1.0,
    wFuel: 0.5,
    wRisk: 2.0,
  },
  setCostWeight: (key, value) =>
    set((state) => ({
      costWeights: { ...state.costWeights, [key]: value },
    })),

  /* ── Vessel Configuration ── */
  vesselConfig: {
    type: 'PC7',
    speed: 12,           // knots
    fuelCapacity: 500,   // metric tons
  },
  setVesselConfig: (config) =>
    set((state) => ({
      vesselConfig: { ...state.vesselConfig, ...config },
    })),

  /* ── Computed Routes ── */
  routes: null,            // Normalized POST /route response (routeService.normalizeRouteResult): the raw fields plus `list`
  lastRequest: null,       // { origin, destination, originName, destinationName, departDate, bergLimit, weights } behind `routes`
  selectedRouteId: null,   // Profile key, e.g. 'balanced' | 'min_ice' | 'min_time' | 'great_circle' | 'persistence_route'
  hoveredRouteId: null,    // Profile key under the pointer in a list or on the map
  focusedLegIndex: null,   // Guidance leg number being shown on the map
  isCalculating: false,
  calculationError: null,  // Human-readable reason the last calculation failed

  setRoutes: (routes, request = null) =>
    set((s) => ({
      routes,
      lastRequest: request,
      calculationError: null,
      selectedRouteId: pickDefaultRoute(routes, s.preferredProfile),
      hoveredRouteId: null,
      focusedLegIndex: null,
    })),
  selectRoute: (id) => set({ selectedRouteId: id, focusedLegIndex: null }),
  setHoveredRoute: (id) => set({ hoveredRouteId: id }),
  focusLeg: (index) => set({ focusedLegIndex: index }),
  setCalculating: (calculating) => set({ isCalculating: calculating }),
  setCalculationError: (calculationError) => set({ calculationError }),
  clearRoutes: () =>
    set({
      routes: null,
      lastRequest: null,
      selectedRouteId: null,
      hoveredRouteId: null,
      focusedLegIndex: null,
      calculationError: null,
    }),

  /* ── Active Mission Route ── */
  activeRoute: null,     // Currently executing route
  setActiveRoute: (route) => set({ activeRoute: route }),

  /* ── Clear All ── */
  clearPlanning: () =>
    set({
      origin: null,
      destination: null,
      routes: null,
      lastRequest: null,
      selectedRouteId: null,
      hoveredRouteId: null,
      focusedLegIndex: null,
      isCalculating: false,
      calculationError: null,
    }),
}));

export default useRouteStore;
