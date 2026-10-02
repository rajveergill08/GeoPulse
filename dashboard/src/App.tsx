import {lazy, Suspense, useEffect, useState} from 'react';

import {DashboardHeader} from './components/DashboardHeader';
import {FootfallTimeline} from './components/FootfallTimeline';
import {KpiStrip} from './components/KpiStrip';
import {MobilityMapUnavailable} from './components/MobilityMapUnavailable';
import {ScenarioPanel} from './components/ScenarioPanel';
import {loadDashboardSnapshot} from './data/dashboardData';
import type {CannibalizationFlow, DashboardSnapshot, Daypart} from './data/types';

const MobilityMapBoundary = lazy(() =>
  import('./components/MobilityMapBoundary').then((module) => ({
    default: module.MobilityMapBoundary
  }))
);
const hasMapboxToken = Boolean(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim());

function isHourInDaypart(hour: number, daypart: Daypart): boolean {
  switch (daypart) {
    case 'morning_commute':
      return hour >= 5 && hour <= 9;
    case 'midday':
      return hour >= 10 && hour <= 15;
    case 'evening_commute':
      return hour >= 16 && hour <= 19;
    case 'off_peak':
      return hour < 5 || hour >= 20;
  }
}

function initialHourForScenario(snapshot: DashboardSnapshot, flow: CannibalizationFlow): number {
  const selectedStores = new Set([flow.existingStoreId, flow.candidateStoreId]);
  const reportedHours = new Set<number>();

  for (const row of snapshot.hourlyFootfall) {
    if (row.trafficDateLocal === flow.trafficDateLocal && selectedStores.has(row.storeId)) {
      reportedHours.add(row.hourLocal);
    }
  }

  const sortedHours = [...reportedHours].sort((left, right) => left - right);
  return sortedHours.find((hour) => isHourInDaypart(hour, flow.daypart)) ?? sortedHours[0] ?? 0;
}

export default function App() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string | null>(null);
  const [hourSelection, setHourSelection] = useState<{scenarioId: string; hour: number} | null>(null);
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
  const selectedHour =
    hourSelection?.scenarioId === selectedFlow.scenarioId
      ? hourSelection.hour
      : initialHourForScenario(snapshot, selectedFlow);

  return (
    <div className="dashboard-shell">
      <DashboardHeader metadata={snapshot.metadata} />
      <main className="dashboard-main">
        <KpiStrip flow={selectedFlow} />
        <FootfallTimeline
          snapshot={snapshot}
          flow={selectedFlow}
          selectedHour={selectedHour}
          onHourChange={(hour) => setHourSelection({scenarioId: selectedFlow.scenarioId, hour})}
        />
        <div className="dashboard-grid">
          <ScenarioPanel
            snapshot={snapshot}
            selectedFlow={selectedFlow}
            onScenarioChange={(scenarioId) => {
              setSelectedScenarioId(scenarioId);
              setHourSelection(null);
            }}
          />
          {hasMapboxToken ? (
            <Suspense fallback={<div className="map-loading">Loading geospatial renderer…</div>}>
              <MobilityMapBoundary
                snapshot={snapshot}
                flow={selectedFlow}
                selectedHour={selectedHour}
              />
            </Suspense>
          ) : (
            <MobilityMapUnavailable
              snapshot={snapshot}
              flow={selectedFlow}
              selectedHour={selectedHour}
            />
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
