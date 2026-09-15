/* useSelectedRoute — the alternative the user has selected, with its legs.

   Geometry (legs, along-track distances) is cached per route object in
   utils/navigation, so every component calling this shares one computation. */

import { useMemo } from 'react';
import useRouteStore from '@stores/useRouteStore';
import { getRouteGeometry } from '@utils/navigation';

export function useSelectedRoute() {
  const result = useRouteStore((s) => s.routes);
  const selectedId = useRouteStore((s) => s.selectedRouteId);

  const route = useMemo(
    () => result?.list?.find((r) => r.key === selectedId) ?? null,
    [result, selectedId]
  );
  const geometry = useMemo(() => getRouteGeometry(route), [route]);

  return { result, route, geometry };
}

export default useSelectedRoute;
