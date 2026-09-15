/* PanelSection — a collapsible block in the map workspace's side panels. */

import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';

export default function PanelSection({
  title, icon: Icon, meta, defaultOpen = true, children, className = '',
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className={`map-panel-section ps${open ? ' is-open' : ''} ${className}`.trim()}>
      <button type="button" className="ps-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {Icon && <Icon size={12} />}
        <span className="ps-title">{title}</span>
        {meta && <span className="ps-meta">{meta}</span>}
        <ChevronDown size={12} className="ps-chevron" />
      </button>
      {open && <div className="ps-body">{children}</div>}
    </section>
  );
}
