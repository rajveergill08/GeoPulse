import {comparableFlows} from '../data/comparableFlows';
import {findStore} from '../data/dashboardData';
import {formatDaypart, formatInteger, formatPercent, formatTrafficDate} from '../data/formatters';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';

interface ScenarioComparisonProps {
  snapshot: DashboardSnapshot;
  selectedFlow: CannibalizationFlow;
  onScenarioChange: (scenarioId: string) => void;
}

export function ScenarioComparison({
  snapshot,
  selectedFlow,
  onScenarioChange
}: ScenarioComparisonProps) {
  const flows = comparableFlows(snapshot, selectedFlow);
  if (flows.length < 2) {
    return null;
  }

  const existingStore = findStore(snapshot, selectedFlow.existingStoreId);

  return (
    <section className="scenario-comparison" aria-labelledby="comparison-heading">
      <div className="scenario-comparison__intro">
        <div>
          <p className="eyebrow">Side-by-side evidence</p>
          <h2 id="comparison-heading">Compare candidate catchments</h2>
        </div>
        <p>
          Against {existingStore.storeName} · {formatTrafficDate(selectedFlow.trafficDateLocal)} ·{' '}
          {formatDaypart(selectedFlow.daypart)}
        </p>
      </div>

      <div className="scenario-comparison__options" role="group" aria-label="Candidate scenarios">
        {flows.map((flow) => {
          const candidate = findStore(snapshot, flow.candidateStoreId);
          const selected = flow.scenarioId === selectedFlow.scenarioId;
          return (
            <button
              className={`scenario-comparison__option${selected ? ' scenario-comparison__option--selected' : ''}`}
              type="button"
              key={flow.scenarioId}
              aria-pressed={selected}
              onClick={() => onScenarioChange(flow.scenarioId)}
            >
              <span className="scenario-comparison__option-top">
                <strong>{candidate.storeName}</strong>
                <span>{selected ? 'Selected' : 'View scenario'}</span>
              </span>
              <span className="scenario-comparison__measures">
                <span>
                  <small>Existing catchment overlap</small>
                  <strong>{formatPercent(flow.cannibalizationRate)}</strong>
                  <small>
                    {formatInteger(flow.sharedVisitors)} of{' '}
                    {formatInteger(flow.existingStoreUniqueVisitors)} visitors
                  </small>
                </span>
                <span>
                  <small>Candidate-only reach</small>
                  <strong>{formatInteger(flow.incrementalCandidateVisitors)}</strong>
                  <small>
                    of {formatInteger(flow.candidateStoreUniqueVisitors)} candidate visitors
                  </small>
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <p className="scenario-comparison__caveat">
        Synthetic GPS catchment estimates, not measured diversion or sales. Zero observed overlap
        does not prove no movement.
      </p>
    </section>
  );
}
