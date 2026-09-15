/* useProvenance — dataset provenance and coverage reporting. */

import { useQuery } from '@tanstack/react-query';
import provenanceService from '@services/provenanceService';
import { retryUnlessMissing } from '@services/api';

export function useProvenance() {
  return useQuery({
    queryKey: ['data-provenance'],
    queryFn: provenanceService.getProvenance,
    staleTime: 10 * 60 * 1000,
  });
}

export function useLiveBergs() {
  return useQuery({
    queryKey: ['bergs-live'],
    queryFn: provenanceService.getLiveBergs,
    staleTime: 60 * 60 * 1000,   // weekly feed — no point polling it
    retry: retryUnlessMissing,
  });
}

export default useProvenance;
