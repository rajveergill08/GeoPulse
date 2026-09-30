import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from './dashboardData';
import type {DashboardSnapshot} from './types';

function validSnapshot(): DashboardSnapshot {
  return {
    metadata: {
      source: 'GEOPULSE.ANALYTICS.FCT_STORE_CANNIBALIZATION',
      refreshedAt: '2026-09-25T06:30:00Z',
      timezone: 'UTC',
      retailTimezone: 'Asia/Kolkata',
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
        trafficDateLocal: '2026-09-22',
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

  it('rejects fractional or unsafe visitor counts', () => {
    const fractional = validSnapshot();
    fractional.flows[0].sharedVisitors = 1.5;
    expect(() => parseDashboardSnapshot(fractional)).toThrow(
      'Dashboard response contains invalid cannibalization metrics.'
    );

    const unsafe = validSnapshot();
    unsafe.flows[0].existingStoreUniqueVisitors = Number.MAX_SAFE_INTEGER + 1;
    expect(() => parseDashboardSnapshot(unsafe)).toThrow(
      'Dashboard response contains invalid cannibalization metrics.'
    );
  });

  it('rejects rates that disagree with the exported visitor counts', () => {
    const snapshot = validSnapshot();
    snapshot.flows[0].cannibalizationRate = 0.5;

    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard response contains invalid cannibalization metrics.'
    );
  });

  it('accepts six-decimal mart rounding at the contract boundary', () => {
    const snapshot = validSnapshot();
    snapshot.flows[0].existingStoreUniqueVisitors = 3;
    snapshot.flows[0].candidateStoreUniqueVisitors = 3;
    snapshot.flows[0].sharedVisitors = 1;
    snapshot.flows[0].incrementalCandidateVisitors = 2;
    snapshot.flows[0].cannibalizationRate = 0.333333;
    snapshot.flows[0].candidateOverlapRate = 0.333333;
    snapshot.flows[0].candidateIncrementalReachRate = 0.666667;

    expect(parseDashboardSnapshot(snapshot)).toEqual(snapshot);
  });

  it('rejects a flow that references an unknown store', () => {
    const snapshot = validSnapshot();
    snapshot.flows[0].candidateStoreId = 'store_missing';

    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard flow references a store that is not in the response.'
    );
  });

  it('requires the retail timezone used by local dates and dayparts', () => {
    const snapshot = validSnapshot();
    snapshot.metadata.retailTimezone = '';

    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard response contains invalid store metadata.'
    );
  });
});
