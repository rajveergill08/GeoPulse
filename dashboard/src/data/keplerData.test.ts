import {describe, expect, it} from 'vitest';

import {buildKeplerDatasets, FLOWS_DATASET_ID, STORES_DATASET_ID} from './keplerData';
import type {CannibalizationFlow, DashboardSnapshot} from './types';

const flow: CannibalizationFlow = {
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
};

const snapshot: DashboardSnapshot = {
  metadata: {
    source: 'test',
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
  flows: [flow]
};

describe('buildKeplerDatasets', () => {
  it('creates stable store and movement datasets for Kepler.gl', () => {
    const datasets = buildKeplerDatasets(snapshot, flow);

    expect(datasets.map((dataset) => dataset.info.id)).toEqual([
      STORES_DATASET_ID,
      FLOWS_DATASET_ID
    ]);
    expect(datasets[0].data.rows).toHaveLength(2);
    expect(datasets[1].data.rows[0]).toEqual([
      'morning-comparison',
      'Store A',
      'Store B',
      12.9756,
      77.6066,
      12.9719,
      77.607,
      3,
      0.3,
      'morning_commute',
      '2026-09-22'
    ]);
  });

  it('uses coordinate field names that Kepler.gl can detect', () => {
    const datasets = buildKeplerDatasets(snapshot, flow);
    const flowFields = datasets[1].data.fields.map((field) => field.name);

    expect(flowFields).toEqual(
      expect.arrayContaining([
        'origin_latitude',
        'origin_longitude',
        'destination_latitude',
        'destination_longitude'
      ])
    );
  });
});
