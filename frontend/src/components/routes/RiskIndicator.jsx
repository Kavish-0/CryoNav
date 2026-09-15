/* RiskIndicator — a small Low / Moderate / High pill.

   Purely presentational: callers decide the level (see utils/routeAssessment)
   so the same pill can label berg risk, sea-ice exposure or a proximity screen. */

import React from 'react';
import { RISK_LEVEL_LABELS } from '@utils/routeAssessment';
import '@styles/routes.css';

export default function RiskIndicator({ level = 'unknown', label, prefix, title }) {
  const cls = RISK_LEVEL_LABELS[level] ? level : 'unknown';
  return (
    <span className={`risk-pill is-${cls}`} title={title}>
      <span className="risk-pill-dot" aria-hidden="true" />
      {prefix && <span className="risk-pill-prefix">{prefix}</span>}
      {label ?? RISK_LEVEL_LABELS[cls]}
    </span>
  );
}
