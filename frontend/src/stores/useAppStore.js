/* ═══════════════════════════════════════════════════════════════
   useAppStore — Global application state
   ═══════════════════════════════════════════════════════════════ */

import { create } from 'zustand';

const useAppStore = create((set) => ({
  /* ── Selected Date ──
     Starts empty on purpose. This used to seed today's date, so every page
     fired /observed, /bergs and /forecast for a day outside the 2017–2024
     cube before TopBar could pull it back in range — silently wrong answers
     before the backend validated dates, and a burst of 400s after. TopBar
     sets it from GET /demo-dates as soon as the range is known, and every
     data hook stays idle until then (enabled: Boolean(date)). */
  selectedDate: null,
  setSelectedDate: (date) => set({ selectedDate: date }),

  /* ── View Mode ── */
  viewMode: 'live',  // 'live' | 'historical' | 'simulation'
  setViewMode: (mode) => set({ viewMode: mode }),

  /* ── Sidebar ── */
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  /* ── Active Page ── */
  activePage: 'dashboard',
  setActivePage: (page) => set({ activePage: page }),

  /* ── Connection Status ── */
  isConnected: false,
  setConnected: (connected) => set({ isConnected: connected }),

  /* ── Global Loading ── */
  isGlobalLoading: false,
  setGlobalLoading: (loading) => set({ isGlobalLoading: loading }),
}));

export default useAppStore;
