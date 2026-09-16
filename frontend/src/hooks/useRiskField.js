/* useRiskField — the router's iceberg-risk field for a date and passage day.

   Propagating the drift ensemble is expensive server-side, so this is only
   fetched when the Risk Zones layer is on (pass a falsy date to stay idle)
   and is cached for the session. A backend without the endpoint 404s once
   and is not retried. */

import { useQuery } from '@tanstack/react-query';
import riskFieldService from '@services/riskFieldService';
import { retryUnlessMissing } from '@services/api';

export function useRiskField(date, lead = 1, limit = 8) {
  return useQuery({
    queryKey: ['risk-field', date, lead, limit],
    queryFn: () => riskFieldService.getRiskField(date, lead, limit),
    enabled: Boolean(date),
    staleTime: 10 * 60 * 1000,
    retry: retryUnlessMissing,
  });
}

export default useRiskField;
