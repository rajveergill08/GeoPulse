import {findStore} from '../data/dashboardData';
import {formatPercent} from '../data/formatters';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {MobilityMapHeader} from './MobilityMapHeader';

interface MobilityMapUnavailableProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
  selectedHour: number;
}

export function MobilityMapUnavailable({
  snapshot,
  flow,
  selectedHour
}: MobilityMapUnavailableProps) {
  const existingStore = findStore(snapshot, flow.existingStoreId);
  const candidateStore = findStore(snapshot, flow.candidateStoreId);
  const reportedStores = [flow.existingStoreId, flow.candidateStoreId].filter((storeId) =>
    snapshot.hourlyFootfall.some(
      (row) =>
        row.storeId === storeId &&
        row.trafficDateLocal === flow.trafficDateLocal &&
        row.hourLocal === selectedHour
    )
  ).length;

  return (
    <section className="map-card" aria-labelledby="map-heading">
      <MobilityMapHeader />
      <div className="map-viewport map-preview">
        <svg
          className="map-preview__link"
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
          <path d="M230 335 L720 265" />
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
          <span>daypart traffic at risk</span>
        </div>

        <p className="map-preview__hour-note" role="status">
          {String(selectedHour).padStart(2, '0')}:00 · Hourly data reported for {reportedStores} of 2
          selected stores
        </p>

        <div className="map-token-notice" role="status">
          Add <code>VITE_MAPBOX_ACCESS_TOKEN</code> locally to activate the interactive Kepler.gl
          basemap. No token is stored in this repository.
        </div>
      </div>
    </section>
  );
}
