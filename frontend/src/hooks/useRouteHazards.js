/* useRouteHazards — sea ice and icebergs along the selected route.

   Uses data the backend already serves, for the route's own departure
   date: the observed sea-ice field (GET /observed + GET /grid) and the same
   berg drift ensembles the router considered (GET /bergs, with the
   request's berg_limit and a horizon long enough to cover the voyage).
   The screening itself runs in utils/navigation. */

import { useMemo } from 'react';
import useRouteStore from '@stores/useRouteStore';
import { useGrid } from './useGrid';
import { useObserved } from './useObserved';
import { useIcebergsMeta } from './useIcebergs';
import {
  getRouteGeometry, createGridLocator, sampleSicAlongRoute, assessBergProximity,
} from '@utils/navigation';

/** GET /bergs accepts up to 90 days; 60 keeps the ensemble request reasonable. */
const MAX_DRIFT_DAYS = 60;

export function useRouteHazards(route, result) {
  const departDate = result?.depart_date ?? null;
  const bergLimit = useRouteStore((s) => s.lastRequest?.bergLimit ?? 8);
  const active = Boolean(route?.success && departDate);
  const horizonDays = active && route.timeH
    ? Math.min(MAX_DRIFT_DAYS, Math.max(1, Math.ceil(route.timeH / 24)))
    : 7;

  const { data: grid, isError: gridError } = useGrid();
  const observed = useObserved(active ? departDate : null);
  const bergs = useIcebergsMeta(active ? departDate : null, horizonDays, bergLimit);
  const geometry = useMemo(() => getRouteGeometry(route), [route]);

  const exposure = useMemo(() => {
    if (!active || !geometry || !grid || !observed.data?.sic) return null;
    return sampleSicAlongRoute(geometry, createGridLocator(grid), observed.data.sic, grid.land_mask);
  }, [active, geometry, grid, observed.data]);

  const proximity = useMemo(() => {
    if (!active || !geometry || !bergs.data?.bergs) return null;
    return assessBergProximity(bergs.data.bergs, geometry, route.timeH);
  }, [active, geometry, bergs.data, route]);

  return {
    active,
    departDate,
    horizonDays,
    bergLimit,
    exposure,
    proximity,
    bergSource: bergs.data?.source ?? null,
    nEnsemble: bergs.data?.n_ensemble ?? null,
    loading: {
      sic: active && (observed.isLoading || (!grid && !gridError)),
      bergs: active && bergs.isLoading,
    },
    errors: {
      sic: active && Boolean(observed.isError || gridError),
      bergs: active && Boolean(bergs.isError),
    },
  };
}

export default useRouteHazards;
