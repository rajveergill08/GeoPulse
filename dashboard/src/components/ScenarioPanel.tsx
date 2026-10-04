import {findStore} from '../data/dashboardData';
import {formatDaypart, formatInteger, formatTrafficDate} from '../data/formatters';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';

interface ScenarioPanelProps {
  snapshot: DashboardSnapshot;
  selectedFlow: CannibalizationFlow;
  onScenarioChange: (scenarioId: string) => void;
}

export function ScenarioPanel({
  snapshot,
  selectedFlow,
  onScenarioChange
}: ScenarioPanelProps) {
  const existingStore = findStore(snapshot, selectedFlow.existingStoreId);
  const candidateStore = findStore(snapshot, selectedFlow.candidateStoreId);

  return (
    <aside className="scenario-panel" aria-labelledby="scenario-heading">
      <div>
        <p className="eyebrow">Location comparison</p>
        <h2 id="scenario-heading">Evaluate candidate</h2>
      </div>

      <label className="scenario-select">
        <span>Scenario</span>
        <select
          value={selectedFlow.scenarioId}
          onChange={(event) => onScenarioChange(event.target.value)}
        >
          {snapshot.flows.map((flow) => {
            const candidate = findStore(snapshot, flow.candidateStoreId);
            return (
              <option key={flow.scenarioId} value={flow.scenarioId}>
                {candidate.storeName} · {formatDaypart(flow.daypart)}
              </option>
            );
          })}
        </select>
      </label>

      <dl className="scenario-facts">
        <div>
          <dt>Existing store</dt>
          <dd>{existingStore.storeName}</dd>
        </div>
        <div>
          <dt>Candidate</dt>
          <dd>{candidateStore.storeName}</dd>
        </div>
        <div>
          <dt>Traffic window</dt>
          <dd>
            {formatDaypart(selectedFlow.daypart)} ·{' '}
            {formatTrafficDate(selectedFlow.trafficDateLocal)}
          </dd>
        </div>
        <div>
          <dt>Catchment</dt>
          <dd>{candidateStore.catchmentRadiusM} m radius</dd>
        </div>
      </dl>

      <section className="directional-note" aria-labelledby="directional-heading">
        <h3 id="directional-heading">Observed ping ordering</h3>
        <p className="directional-note__count">
          <strong>{formatInteger(selectedFlow.orderedCandidateToExistingVisitors)}</strong> of{' '}
          <strong>{formatInteger(selectedFlow.sharedVisitors)}</strong> shared visitors
        </p>
        <p>
          Counts a shared visitor only when a candidate-only ping precedes a later existing-only
          ping on the selected retail-local date and daypart. Same-ping catchment overlap is
          excluded.
        </p>
        <small>
          This is not a traced route, interception, or lost sale. Zero does not prove no movement.
        </small>
      </section>

      <div className="decision-note">
        <span className="decision-note__icon" aria-hidden="true">
          i
        </span>
        <p>
          Overlap is a traffic-at-risk proxy. Confirm the location decision with transactions,
          conversion, and pre/post-opening evidence.
        </p>
      </div>

      <div className="source-note">
        <span>Source</span>
        <p>{snapshot.metadata.source}</p>
        <small>
          Retail time: {snapshot.metadata.retailTimezone} · Refresh time:{' '}
          {snapshot.metadata.timezone}
        </small>
      </div>
    </aside>
  );
}
