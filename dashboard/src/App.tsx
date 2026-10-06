import {lazy, Suspense, useEffect, useState} from 'react';

import {DashboardHeader} from './components/DashboardHeader';
import {FootfallTimeline} from './components/FootfallTimeline';
import {KpiStrip} from './components/KpiStrip';
import {MobilityMapUnavailable} from './components/MobilityMapUnavailable';
import {ScenarioComparison} from './components/ScenarioComparison';
import {ScenarioPanel} from './components/ScenarioPanel';
import {loadDashboardSnapshot} from './data/dashboardData';
import {nextHour} from './data/hourPlayback';
import type {CannibalizationFlow, DashboardSnapshot, Daypart} from './data/types';

const MobilityMapBoundary = lazy(() =>
  import('./components/MobilityMapBoundary').then((module) => ({
    default: module.MobilityMapBoundary
  }))
);
const hasMapboxToken = Boolean(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim());
const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';
const PLAYBACK_INTERVAL_MS = 1000;

function initialReducedMotionPreference(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(REDUCED_MOTION_QUERY).matches
    : false;
}

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
  const [isPlaying, setIsPlaying] = useState(false);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(initialReducedMotionPreference);
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

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      return;
    }

    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);
    const onPreferenceChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
      if (event.matches) {
        setIsPlaying(false);
      }
    };

    mediaQuery.addEventListener('change', onPreferenceChange);
    return () => mediaQuery.removeEventListener('change', onPreferenceChange);
  }, []);

  useEffect(() => {
    const pauseWhenHidden = () => {
      if (document.hidden) {
        setIsPlaying(false);
      }
    };

    document.addEventListener('visibilitychange', pauseWhenHidden);
    return () => document.removeEventListener('visibilitychange', pauseWhenHidden);
  }, []);

  useEffect(() => {
    if (!isPlaying || prefersReducedMotion || !snapshot || !selectedScenarioId) {
      return;
    }

    const flow = snapshot.flows.find((item) => item.scenarioId === selectedScenarioId);
    if (!flow) {
      return;
    }

    const initialHour = initialHourForScenario(snapshot, flow);
    const timer = window.setInterval(() => {
      setHourSelection((previous) => ({
        scenarioId: selectedScenarioId,
        hour: nextHour(
          previous?.scenarioId === selectedScenarioId ? previous.hour : initialHour
        )
      }));
    }, PLAYBACK_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [isPlaying, prefersReducedMotion, selectedScenarioId, snapshot]);

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
  const selectScenario = (scenarioId: string) => {
    setIsPlaying(false);
    setSelectedScenarioId(scenarioId);
    setHourSelection(null);
  };
  const selectHour = (hour: number) => {
    setIsPlaying(false);
    setHourSelection({scenarioId: selectedFlow.scenarioId, hour});
  };

  return (
    <div className="dashboard-shell">
      <DashboardHeader metadata={snapshot.metadata} />
      <main className="dashboard-main">
        <ScenarioComparison
          snapshot={snapshot}
          selectedFlow={selectedFlow}
          onScenarioChange={selectScenario}
        />
        <KpiStrip flow={selectedFlow} />
        <FootfallTimeline
          snapshot={snapshot}
          flow={selectedFlow}
          selectedHour={selectedHour}
          onHourChange={selectHour}
          isPlaying={isPlaying}
          playbackDisabled={prefersReducedMotion}
          onPlaybackToggle={() => setIsPlaying((current) => !current)}
        />
        <div className="dashboard-grid">
          <ScenarioPanel
            snapshot={snapshot}
            selectedFlow={selectedFlow}
            onScenarioChange={selectScenario}
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
              isPlaying={isPlaying}
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
