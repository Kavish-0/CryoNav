/* useRouteCalculation — POST /route, wired into the route store.

   useRouteCalculation is the plain React Query mutation. usePlanRoutes is
   what the UI calls: it reads the planner inputs from useRouteStore and the
   analysis date from useAppStore, and writes the result back to the store,
   so a calculation started from a map popup and one started from the
   planner land in the same place. */

import { useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import routeService from '@services/routeService';
import useRouteStore from '@stores/useRouteStore';
import useAppStore from '@stores/useAppStore';

/**
 * Computes routes for an origin/destination/date combo.
 * Resolves to the normalized response (see routeService.normalizeRouteResult).
 */
export function useRouteCalculation() {
  return useMutation({
    mutationFn: (params) => routeService.calculateRoute(params),
  });
}

/** Human-readable reason a route request failed. */
export function routeErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (error?.code === 'ECONNABORTED') return 'Route calculation timed out after 3 minutes.';
  if (!error?.response) return 'Could not reach the CryoNav backend.';
  if (error.response.status >= 500) {
    return `The routing engine failed (HTTP ${error.response.status}). Check the backend log for the traceback.`;
  }
  return error?.message || 'Route calculation failed.';
}

/**
 * Plan routes from the planner state.
 *
 * `plan(overrides)` accepts { origin, destination, departDate } to use
 * instead of the stored values — used when an endpoint is picked on the map
 * and the calculation should start with it immediately.
 */
export function usePlanRoutes() {
  const { mutateAsync } = useRouteCalculation();
  const isCalculating = useRouteStore((s) => s.isCalculating);

  const plan = useCallback(async (overrides = {}) => {
    const store = useRouteStore.getState();
    const origin = overrides.origin ?? store.origin;
    const destination = overrides.destination ?? store.destination;
    const departDate = overrides.departDate ?? useAppStore.getState().selectedDate;
    if (!origin || !destination || origin.id === destination.id || store.isCalculating) return null;

    const request = {
      origin: origin.id,
      destination: destination.id,
      originName: origin.name,
      destinationName: destination.name,
      departDate,
      bergLimit: store.bergLimit,
      weights: { ...store.costWeights },
    };

    store.setCalculating(true);
    store.setCalculationError(null);
    try {
      const result = await mutateAsync({
        origin: request.origin,
        destination: request.destination,
        departDate,
        bergLimit: request.bergLimit,
        wTime: request.weights.wTime,
        wFuel: request.weights.wFuel,
        wRisk: request.weights.wRisk,
      });
      useRouteStore.getState().setRoutes(result, request);
      return result;
    } catch (error) {
      useRouteStore.getState().setCalculationError(routeErrorMessage(error));
      return null;
    } finally {
      useRouteStore.getState().setCalculating(false);
    }
  }, [mutateAsync]);

  return { plan, isCalculating };
}
