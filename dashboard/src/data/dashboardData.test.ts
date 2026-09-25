import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from './dashboardData';
import type {DashboardSnapshot} from './types';

function validSnapshot(): DashboardSnapshot {
  return {
    metadata: {
      source: 'GEOPULSE.ANALYTICS.FCT_STORE_CANNIBALIZATION',
      refreshedAt: '2026-09-25T06:30:00Z',
      timezone: 'UTC',
      synthetic: true
    },
    stores: [
      {
        storeId: 'store_a',
        storeName: 'Store A',
        status: 'existing',
        latitude: 12.9756,
        longitude: 77.6066,
        catchmentRadiusM: 500
      },
      {
        storeId: 'store_b',
        storeName: 'Store B',
        status: 'proposed',
        latitude: 12.9719,
        longitude: 77.607,
        catchmentRadiusM: 500
      }
    ],
    flows: [
      {
        scenarioId: 'morning-comparison',
        existingStoreId: 'store_a',
        candidateStoreId: 'store_b',
        trafficDateUtc: '2026-09-22',
        daypart: 'morning_commute',
        existingStoreUniqueVisitors: 10,
        candidateStoreUniqueVisitors: 4,
        sharedVisitors: 3,
        incrementalCandidateVisitors: 1,
        cannibalizationRate: 0.3,
        candidateOverlapRate: 0.75,
        candidateIncrementalReachRate: 0.25
      }
    ]
  };
}

describe('parseDashboardSnapshot', () => {
  it('accepts a consistent aggregated mobility snapshot', () => {
    const snapshot = validSnapshot();

    expect(parseDashboardSnapshot(snapshot)).toEqual(snapshot);
  });

  it('rejects mathematically inconsistent incremental visitors', () => {
    const snapshot = validSnapshot();
    snapshot.flows[0].incrementalCandidateVisitors = 2;

    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard response contains invalid cannibalization metrics.'
    );
  });

  it('rejects a flow that references an unknown store', () => {
    const snapshot = validSnapshot();
    snapshot.flows[0].candidateStoreId = 'store_missing';

    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard flow references a store that is not in the response.'
    );
  });
});
