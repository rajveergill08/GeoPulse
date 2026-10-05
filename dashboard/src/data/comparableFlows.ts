import type {CannibalizationFlow, DashboardSnapshot} from './types';

/** Compare candidates only against the same existing store and retail-local window. */
export function comparableFlows(
  snapshot: DashboardSnapshot,
  selectedFlow: CannibalizationFlow
): CannibalizationFlow[] {
  return snapshot.flows.filter(
    (flow) =>
      flow.existingStoreId === selectedFlow.existingStoreId &&
      flow.trafficDateLocal === selectedFlow.trafficDateLocal &&
      flow.daypart === selectedFlow.daypart
  );
}
