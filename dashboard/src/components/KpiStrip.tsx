import {formatInteger, formatPercent} from '../data/formatters';
import type {CannibalizationFlow} from '../data/types';

interface KpiStripProps {
  flow: CannibalizationFlow;
}

interface KpiCardProps {
  label: string;
  value: string;
  detail: string;
  accent?: boolean;
}

function KpiCard({label, value, detail, accent = false}: KpiCardProps) {
  return (
    <article className={`kpi-card${accent ? ' kpi-card--accent' : ''}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

export function KpiStrip({flow}: KpiStripProps) {
  return (
    <section className="kpi-strip" aria-label="Cannibalization summary">
      <KpiCard
        label="Existing traffic at risk"
        value={formatPercent(flow.cannibalizationRate)}
        detail={`${formatInteger(flow.sharedVisitors)} of ${formatInteger(
          flow.existingStoreUniqueVisitors
        )} visitors overlap`}
        accent
      />
      <KpiCard
        label="Shared visitors"
        value={formatInteger(flow.sharedVisitors)}
        detail="Observed in both catchments"
      />
      <KpiCard
        label="Candidate overlap"
        value={formatPercent(flow.candidateOverlapRate)}
        detail={`${formatInteger(flow.sharedVisitors)} of ${formatInteger(
          flow.candidateStoreUniqueVisitors
        )} candidate visitors`}
      />
      <KpiCard
        label="Incremental reach"
        value={formatPercent(flow.candidateIncrementalReachRate)}
        detail={`${formatInteger(flow.incrementalCandidateVisitors)} candidate-only visitor`}
      />
    </section>
  );
}
