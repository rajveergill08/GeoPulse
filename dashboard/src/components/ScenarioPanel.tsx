import {findStore} from '../data/dashboardData';
import {formatDaypart, formatTrafficDate} from '../data/formatters';
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
            {formatTrafficDate(selectedFlow.trafficDateUtc)}
          </dd>
        </div>
        <div>
          <dt>Catchment</dt>
          <dd>{candidateStore.catchmentRadiusM} m radius</dd>
        </div>
      </dl>

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
        <small>Canonical timestamps: {snapshot.metadata.timezone}</small>
      </div>
    </aside>
  );
}
