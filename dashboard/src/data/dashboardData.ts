import type {CannibalizationFlow, DashboardSnapshot, StoreMetric} from './types';

const DEFAULT_DATA_URL = '/data/geopulse-dashboard.json';
const snapshotRequests = new Map<string, Promise<DashboardSnapshot>>();

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isRate(value: unknown): value is number {
  return isFiniteNumber(value) && value >= 0 && value <= 1;
}

function isStore(value: unknown): value is StoreMetric {
  if (!isRecord(value)) {
    return false;
  }

  return (
    typeof value.storeId === 'string' &&
    typeof value.storeName === 'string' &&
    ['existing', 'proposed', 'candidate'].includes(String(value.status)) &&
    isFiniteNumber(value.latitude) &&
    value.latitude >= -90 &&
    value.latitude <= 90 &&
    isFiniteNumber(value.longitude) &&
    value.longitude >= -180 &&
    value.longitude <= 180 &&
    isFiniteNumber(value.catchmentRadiusM) &&
    value.catchmentRadiusM > 0
  );
}

function isFlow(value: unknown): value is CannibalizationFlow {
  if (!isRecord(value)) {
    return false;
  }

  const existingVisitors = value.existingStoreUniqueVisitors;
  const candidateVisitors = value.candidateStoreUniqueVisitors;
  const sharedVisitors = value.sharedVisitors;
  const incrementalVisitors = value.incrementalCandidateVisitors;

  return (
    typeof value.scenarioId === 'string' &&
    typeof value.existingStoreId === 'string' &&
    typeof value.candidateStoreId === 'string' &&
    typeof value.trafficDateUtc === 'string' &&
    ['morning_commute', 'midday', 'evening_commute', 'off_peak'].includes(
      String(value.daypart)
    ) &&
    isFiniteNumber(existingVisitors) &&
    existingVisitors > 0 &&
    isFiniteNumber(candidateVisitors) &&
    candidateVisitors > 0 &&
    isFiniteNumber(sharedVisitors) &&
    sharedVisitors >= 0 &&
    sharedVisitors <= existingVisitors &&
    sharedVisitors <= candidateVisitors &&
    isFiniteNumber(incrementalVisitors) &&
    incrementalVisitors === candidateVisitors - sharedVisitors &&
    isRate(value.cannibalizationRate) &&
    isRate(value.candidateOverlapRate) &&
    isRate(value.candidateIncrementalReachRate) &&
    Math.abs(value.candidateOverlapRate + value.candidateIncrementalReachRate - 1) < 0.000001
  );
}

export function parseDashboardSnapshot(value: unknown): DashboardSnapshot {
  if (!isRecord(value) || !isRecord(value.metadata)) {
    throw new Error('Dashboard response is missing metadata.');
  }

  const {metadata} = value;
  const metadataIsValid =
    typeof metadata.source === 'string' &&
    typeof metadata.refreshedAt === 'string' &&
    metadata.timezone === 'UTC' &&
    typeof metadata.synthetic === 'boolean';

  if (!metadataIsValid || !Array.isArray(value.stores) || !value.stores.every(isStore)) {
    throw new Error('Dashboard response contains invalid store metadata.');
  }

  if (!Array.isArray(value.flows) || value.flows.length === 0 || !value.flows.every(isFlow)) {
    throw new Error('Dashboard response contains invalid cannibalization metrics.');
  }

  const storeIds = new Set(value.stores.map((store) => store.storeId));
  const hasMissingStore = value.flows.some(
    (flow) => !storeIds.has(flow.existingStoreId) || !storeIds.has(flow.candidateStoreId)
  );

  if (hasMissingStore) {
    throw new Error('Dashboard flow references a store that is not in the response.');
  }

  return value as unknown as DashboardSnapshot;
}

export function loadDashboardSnapshot(
  url = import.meta.env.VITE_GEOPULSE_DATA_URL || DEFAULT_DATA_URL
): Promise<DashboardSnapshot> {
  const cachedRequest = snapshotRequests.get(url);
  if (cachedRequest) {
    return cachedRequest;
  }

  const request = fetch(url)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`Dashboard data request failed with status ${response.status}.`);
      }
      return response.json() as Promise<unknown>;
    })
    .then(parseDashboardSnapshot)
    .catch((error: unknown) => {
      snapshotRequests.delete(url);
      throw error;
    });

  snapshotRequests.set(url, request);
  return request;
}

export function findStore(snapshot: DashboardSnapshot, storeId: string): StoreMetric {
  const store = snapshot.stores.find((candidate) => candidate.storeId === storeId);
  if (!store) {
    throw new Error(`Store ${storeId} is missing from the dashboard snapshot.`);
  }
  return store;
}
