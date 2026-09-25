import {formatRefreshedAt} from '../data/formatters';
import type {DashboardMetadata} from '../data/types';

interface DashboardHeaderProps {
  metadata: DashboardMetadata;
}

export function DashboardHeader({metadata}: DashboardHeaderProps) {
  return (
    <header className="dashboard-header">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div>
          <p className="eyebrow">Retail mobility intelligence</p>
          <h1>GeoPulse</h1>
        </div>
      </div>

      <div className="header-status" aria-label="Dataset status">
        {metadata.synthetic ? <span className="status-chip">Synthetic demo</span> : null}
        <span className="freshness">Updated {formatRefreshedAt(metadata.refreshedAt)}</span>
      </div>
    </header>
  );
}
