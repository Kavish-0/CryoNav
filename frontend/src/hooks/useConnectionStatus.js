/* ═══════════════════════════════════════════════════════════════
   useConnectionStatus — Drives the TopBar "Connected/Offline" dot
   from real backend reachability.

   The real backend (Arman0212/CryoNav) exposes no WebSocket route, so
   there's no live "connection" to hold open. Instead we periodically
   GET /config (a cheap, always-available route) and treat success/
   failure as the connection signal. This replaces the previous
   WebSocket-driven indicator, which would have shown "Offline" forever
   since no WS endpoint exists to connect to.
   ═══════════════════════════════════════════════════════════════ */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import configService from '@services/configService';
import useAppStore from '@stores/useAppStore';

export function useConnectionStatus() {
  const setConnected = useAppStore((s) => s.setConnected);

  const { isSuccess } = useQuery({
    queryKey: ['health-check'],
    queryFn: configService.ping,
    refetchInterval: 30 * 1000, // poll every 30s
    retry: false,
    staleTime: 0,
  });

  useEffect(() => {
    setConnected(Boolean(isSuccess));
  }, [isSuccess, setConnected]);
}
