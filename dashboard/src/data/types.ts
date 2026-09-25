export type StoreStatus = 'existing' | 'proposed' | 'candidate';

export type Daypart = 'morning_commute' | 'midday' | 'evening_commute' | 'off_peak';

export interface DashboardMetadata {
  source: string;
  refreshedAt: string;
  timezone: 'UTC';
  synthetic: boolean;
}

export interface StoreMetric {
  storeId: string;
  storeName: string;
  status: StoreStatus;
  latitude: number;
  longitude: number;
  catchmentRadiusM: number;
}

export interface CannibalizationFlow {
  scenarioId: string;
  existingStoreId: string;
  candidateStoreId: string;
  trafficDateUtc: string;
  daypart: Daypart;
  existingStoreUniqueVisitors: number;
  candidateStoreUniqueVisitors: number;
  sharedVisitors: number;
  incrementalCandidateVisitors: number;
  cannibalizationRate: number;
  candidateOverlapRate: number;
  candidateIncrementalReachRate: number;
}

export interface DashboardSnapshot {
  metadata: DashboardMetadata;
  stores: StoreMetric[];
  flows: CannibalizationFlow[];
}
