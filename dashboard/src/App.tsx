import {lazy, Suspense, useEffect, useState} from 'react';

import {DashboardHeader} from './components/DashboardHeader';
import {KpiStrip} from './components/KpiStrip';
import {MobilityMapUnavailable} from './components/MobilityMapUnavailable';
import {ScenarioPanel} from './components/ScenarioPanel';
import {loadDashboardSnapshot} from './data/dashboardData';
import type {DashboardSnapshot} from './data/types';

const MobilityMapBoundary = lazy(() =>
  import('./components/MobilityMapBoundary').then((module) => ({
    default: module.MobilityMapBoundary
  }))
);
const hasMapboxToken = Boolean(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim());

export default function App() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isActive = true;

    loadDashboardSnapshot()
      .then((nextSnapshot) => {
        if (!isActive) {
          return;
        }
        setSnapshot(nextSnapshot);
        setSelectedScenarioId(nextSnapshot.flows[0].scenarioId);
      })
      .catch((reason: unknown) => {
        if (isActive) {
          setError(reason instanceof Error ? reason.message : 'Unable to load dashboard data.');
        }
      });

    return () => {
      isActive = false;
    };
  }, []);

  if (error) {
    return (
      <main className="state-page" role="alert">
        <p className="eyebrow">GeoPulse data unavailable</p>
        <h1>The mobility snapshot could not be loaded.</h1>
        <p>{error}</p>
      </main>
    );
  }

  if (!snapshot || !selectedScenarioId) {
    return (
      <main className="state-page" aria-live="polite">
        <div className="loading-pulse" aria-hidden="true" />
        <p className="eyebrow">Preparing spatial evidence</p>
        <h1>Loading GeoPulse…</h1>
      </main>
    );
  }

  const selectedFlow =
    snapshot.flows.find((flow) => flow.scenarioId === selectedScenarioId) ?? snapshot.flows[0];

  return (
    <div className="dashboard-shell">
      <DashboardHeader metadata={snapshot.metadata} />
      <main className="dashboard-main">
        <KpiStrip flow={selectedFlow} />
        <div className="dashboard-grid">
          <ScenarioPanel
            snapshot={snapshot}
            selectedFlow={selectedFlow}
            onScenarioChange={setSelectedScenarioId}
          />
          {hasMapboxToken ? (
            <Suspense fallback={<div className="map-loading">Loading geospatial renderer…</div>}>
              <MobilityMapBoundary snapshot={snapshot} flow={selectedFlow} />
            </Suspense>
          ) : (
            <MobilityMapUnavailable snapshot={snapshot} flow={selectedFlow} />
          )}
        </div>
      </main>
      <footer className="dashboard-footer">
        <span>GeoPulse decision support</span>
        <span>Aggregated mobility only · No real device identifiers</span>
      </footer>
    </div>
  );
}
