import {findStore} from '../data/dashboardData';
import {formatPercent} from '../data/formatters';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {MobilityMapHeader} from './MobilityMapHeader';

interface MobilityMapUnavailableProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
}

export function MobilityMapUnavailable({snapshot, flow}: MobilityMapUnavailableProps) {
  const existingStore = findStore(snapshot, flow.existingStoreId);
  const candidateStore = findStore(snapshot, flow.candidateStoreId);

  return (
    <section className="map-card" aria-labelledby="map-heading">
      <MobilityMapHeader />
      <div className="map-viewport map-preview">
        <svg
          className="map-preview__route"
          viewBox="0 0 900 520"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <defs>
            <linearGradient id="preview-flow" x1="0" x2="1">
              <stop offset="0" stopColor="#42db9c" />
              <stop offset="1" stopColor="#f8b864" />
            </linearGradient>
          </defs>
          <path d="M230 335 C390 70 610 85 720 265" />
          <circle cx="230" cy="335" r="16" className="preview-node preview-node--existing" />
          <circle cx="720" cy="265" r="16" className="preview-node preview-node--candidate" />
        </svg>

        <div className="map-preview__label map-preview__label--existing">
          <span>Existing</span>
          <strong>{existingStore.storeName}</strong>
        </div>
        <div className="map-preview__label map-preview__label--candidate">
          <span>Candidate</span>
          <strong>{candidateStore.storeName}</strong>
        </div>
        <div className="map-preview__risk">
          <strong>{formatPercent(flow.cannibalizationRate)}</strong>
          <span>traffic at risk</span>
        </div>

        <div className="map-token-notice" role="status">
          Add <code>VITE_MAPBOX_ACCESS_TOKEN</code> locally to activate the interactive Kepler.gl
          basemap. No token is stored in this repository.
        </div>
      </div>
    </section>
  );
}
