import type {CannibalizationFlow, DashboardSnapshot, HourlyFootfall, StoreMetric} from './types';

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

function isVisitorCount(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isSafeInteger(value) && value >= 0;
}

function isIsoLocalDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() + 1 === month &&
    date.getUTCDate() === day
  );
}

function isHourlyFootfall(value: unknown): value is HourlyFootfall {
  if (!isRecord(value)) {
    return false;
  }

  return (
    Object.keys(value).length === 5 &&
    typeof value.storeId === 'string' &&
    value.storeId.length > 0 &&
    isIsoLocalDate(value.trafficDateLocal) &&
    typeof value.hourLocal === 'number' &&
    Number.isInteger(value.hourLocal) &&
    value.hourLocal >= 0 &&
    value.hourLocal <= 23 &&
    isVisitorCount(value.uniqueVisitors) &&
    isVisitorCount(value.pingCount) &&
    value.uniqueVisitors <= value.pingCount
  );
}

function matchesRoundedRate(actual: number, expected: number): boolean {
  // The dbt mart rounds each rate to six decimal places before export.
  return Math.abs(actual - expected) <= 0.000001 + Number.EPSILON;
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
  const orderedVisitors = value.orderedCandidateToExistingVisitors;
  const incrementalVisitors = value.incrementalCandidateVisitors;

  return (
    typeof value.scenarioId === 'string' &&
    typeof value.existingStoreId === 'string' &&
    typeof value.candidateStoreId === 'string' &&
    typeof value.trafficDateLocal === 'string' &&
    ['morning_commute', 'midday', 'evening_commute', 'off_peak'].includes(
      String(value.daypart)
    ) &&
    isVisitorCount(existingVisitors) &&
    existingVisitors > 0 &&
    isVisitorCount(candidateVisitors) &&
    candidateVisitors > 0 &&
    isVisitorCount(sharedVisitors) &&
    sharedVisitors <= existingVisitors &&
    sharedVisitors <= candidateVisitors &&
    isVisitorCount(orderedVisitors) &&
    orderedVisitors <= sharedVisitors &&
    isVisitorCount(incrementalVisitors) &&
    incrementalVisitors === candidateVisitors - sharedVisitors &&
    isRate(value.cannibalizationRate) &&
    isRate(value.candidateOverlapRate) &&
    isRate(value.candidateIncrementalReachRate) &&
    matchesRoundedRate(value.cannibalizationRate, sharedVisitors / existingVisitors) &&
    matchesRoundedRate(value.candidateOverlapRate, sharedVisitors / candidateVisitors) &&
    matchesRoundedRate(
      value.candidateIncrementalReachRate,
      incrementalVisitors / candidateVisitors
    ) &&
    matchesRoundedRate(value.candidateOverlapRate + value.candidateIncrementalReachRate, 1)
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
    typeof metadata.retailTimezone === 'string' &&
    metadata.retailTimezone.length > 0 &&
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

  if (!Array.isArray(value.hourlyFootfall) || !value.hourlyFootfall.every(isHourlyFootfall)) {
    throw new Error('Dashboard response contains invalid hourly footfall metrics.');
  }

  const flowDates = new Set(value.flows.map((flow) => flow.trafficDateLocal));
  const hourlyKeys = new Set<string>();
  for (const row of value.hourlyFootfall) {
    if (!storeIds.has(row.storeId) || !flowDates.has(row.trafficDateLocal)) {
      throw new Error('Dashboard hourly footfall references an unknown store or flow date.');
    }

    const key = `${row.storeId}\u0000${row.trafficDateLocal}\u0000${row.hourLocal}`;
    if (hourlyKeys.has(key)) {
      throw new Error('Dashboard hourly footfall contains duplicate store-hour metrics.');
    }
    hourlyKeys.add(key);
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
