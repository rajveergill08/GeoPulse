import {findStore} from '../data/dashboardData';
import {formatInteger, formatTrafficDate} from '../data/formatters';
import type {CannibalizationFlow, DashboardSnapshot, StoreMetric} from '../data/types';

interface FootfallTimelineProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
  selectedHour: number;
  onHourChange: (hour: number) => void;
}

function formatHour(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`;
}

export function FootfallTimeline({
  snapshot,
  flow,
  selectedHour,
  onHourChange
}: FootfallTimelineProps) {
  const selectedStores: StoreMetric[] = [
    findStore(snapshot, flow.existingStoreId),
    findStore(snapshot, flow.candidateStoreId)
  ];

  return (
    <section className="footfall-timeline" aria-labelledby="footfall-heading">
      <div className="footfall-timeline__top">
        <div>
          <p className="eyebrow">Hourly evidence</p>
          <h2 id="footfall-heading">Footfall through the day</h2>
          <p className="footfall-timeline__subtitle">
            {formatTrafficDate(flow.trafficDateLocal)} · {snapshot.metadata.retailTimezone} local time
          </p>
        </div>
        <output className="footfall-timeline__time" htmlFor="footfall-hour">
          {formatHour(selectedHour)}
        </output>
      </div>

      <div className="footfall-timeline__body">
        <div className="footfall-timeline__scrubber">
          <label htmlFor="footfall-hour">Select local hour</label>
          <input
            id="footfall-hour"
            type="range"
            min={0}
            max={23}
            step={1}
            value={selectedHour}
            aria-valuetext={`${formatHour(selectedHour)} ${snapshot.metadata.retailTimezone}`}
            aria-describedby="footfall-explanation"
            onChange={(event) => onHourChange(Number(event.target.value))}
          />
          <div className="footfall-timeline__ticks" aria-hidden="true">
            <span>00:00</span>
            <span>06:00</span>
            <span>12:00</span>
            <span>18:00</span>
            <span>23:00</span>
          </div>
        </div>

        <div className="footfall-timeline__metrics" aria-live="polite" aria-atomic="true">
          {selectedStores.map((store) => {
            const row = snapshot.hourlyFootfall.find(
              (item) =>
                item.storeId === store.storeId &&
                item.trafficDateLocal === flow.trafficDateLocal &&
                item.hourLocal === selectedHour
            );

            return (
              <div className="footfall-timeline__metric" key={store.storeId}>
                <span className="footfall-timeline__store-kind">
                  {store.storeId === flow.existingStoreId ? 'Existing store' : 'Candidate store'}
                </span>
                <span className="footfall-timeline__store-name">{store.storeName}</span>
                <strong>{row ? formatInteger(row.uniqueVisitors) : 'No reported data'}</strong>
                <span className="footfall-timeline__metric-detail">
                  {row
                    ? `unique visitors · ${formatInteger(row.pingCount)} pings`
                    : 'Not reported, not zero visitors'}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <p className="footfall-timeline__explanation" id="footfall-explanation">
        The hour filters reported store catchment counts on the map. The overlap risk above is a
        separate daypart estimate, not an hourly measure. The store-pair link is not a tracked route.
      </p>
    </section>
  );
}
