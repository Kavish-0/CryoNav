/* ═══════════════════════════════════════════════════════════════
   TopBar — Page title, date picker, alerts, connection status
   ═══════════════════════════════════════════════════════════════ */

import React, { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Bell, Calendar } from 'lucide-react';
import useAppStore from '@stores/useAppStore';
import useAlertStore from '@stores/useAlertStore';
import { useDemoDates } from '@hooks/useConfig';

const PAGE_TITLES = {
  '/dashboard': 'Dashboard',
  '/map': 'Antarctic Map',
  '/ice': 'Sea Ice Intelligence',
  '/icebergs': 'Iceberg Tracking',
  '/trajectory': 'Trajectory Analysis',
  '/weather': 'Weather Intelligence',
  '/ocean': 'Ocean Intelligence',
  '/routes': 'Route Planning',
  '/risk': 'Risk Assessment',
  '/simulation': 'Mission Simulation',
  '/analytics': 'Analytics',
  '/alerts': 'Alert Center',
  '/copilot': 'AI Copilot',
  '/settings': 'Settings',
};

export default function TopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const selectedDate = useAppStore((s) => s.selectedDate);
  const setSelectedDate = useAppStore((s) => s.setSelectedDate);
  const isConnected = useAppStore((s) => s.isConnected);
  const unreadCount = useAlertStore((s) => s.unreadCount);

  const pageTitle = PAGE_TITLES[location.pathname] || 'CryoNav';

  /* The cube covers a fixed historical window (2017-2024), but the store
     seeds selectedDate with today's date. Every forecast-backed page then
     asked for data the cube does not contain and failed — /ice was the
     visible casualty. Constrain the picker to what is actually loaded, and
     pull an out-of-range date back in.

     The fallback is the newest demo date rather than range.end because
     /forecast needs date + lead to be in range too: sitting on the last
     day of the cube would still fail for any lead > 0. */
  const { data: dates } = useDemoDates();
  const range = dates?.range;
  const fallbackDate = dates?.demo_dates?.length
    ? dates.demo_dates[dates.demo_dates.length - 1]
    : range?.end;

  useEffect(() => {
    if (!range || !fallbackDate) return;
    // Also covers the initial empty date: the store starts without one so no
    // page requests a day before we know which days the cube holds.
    if (!selectedDate || selectedDate < range.start || selectedDate > range.end) {
      setSelectedDate(fallbackDate);
    }
  }, [range, fallbackDate, selectedDate, setSelectedDate]);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <h1 className="topbar-breadcrumb">{pageTitle}</h1>
      </div>

      <div className="topbar-right">
        {/* ── Date Selector (replaces hardcoded date) ── */}
        <label
          className="topbar-date"
          title={range ? `Select analysis date (data covers ${range.start} to ${range.end})` : 'Select analysis date'}
        >
          <Calendar size={14} />
          <input
            type="date"
            value={selectedDate || ''}
            min={range?.start}
            max={range?.end}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              fontFamily: 'inherit',
              fontSize: 'inherit',
              cursor: 'pointer',
              outline: 'none',
            }}
          />
        </label>

        {/* ── Alerts Button ── */}
        <button
          className="topbar-alert-btn"
          onClick={() => navigate('/alerts')}
          aria-label={`Alerts — ${unreadCount} unread`}
        >
          <Bell size={18} />
          {unreadCount > 0 && (
            <span className="topbar-alert-count">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>

        {/* ── Connection Status ── */}
        <div className="topbar-connection">
          <span className={`connection-dot ${isConnected ? '' : 'disconnected'}`} />
          <span>{isConnected ? 'Connected' : 'Offline'}</span>
        </div>
      </div>
    </header>
  );
}
