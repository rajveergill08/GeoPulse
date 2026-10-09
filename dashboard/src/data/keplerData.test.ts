import {describe, expect, it} from 'vitest';

import {KEPLER_MAP_CONFIG} from './keplerConfig';
import {
  buildKeplerDatasets,
  FLOWS_DATASET_ID,
  H3_FOOTFALL_DATASET_ID,
  HOURLY_FOOTFALL_DATASET_ID,
  STORES_DATASET_ID
} from './keplerData';
import type {CannibalizationFlow, DashboardSnapshot} from './types';

const flow: CannibalizationFlow = {
  scenarioId: 'morning-comparison',
  existingStoreId: 'store_a',
  candidateStoreId: 'store_b',
  trafficDateLocal: '2026-09-22',
  daypart: 'morning_commute',
  existingStoreUniqueVisitors: 10,
  candidateStoreUniqueVisitors: 4,
  sharedVisitors: 3,
  orderedCandidateToExistingVisitors: 0,
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
  flows: [flow],
  hourlyFootfall: [
    {
      storeId: 'store_a',
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 10,
      pingCount: 11
    },
    {
      storeId: 'store_b',
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 4,
      pingCount: 4
    },
    {
      storeId: 'store_a',
      trafficDateLocal: '2026-09-22',
      hourLocal: 18,
      uniqueVisitors: 3,
      pingCount: 3
    }
  ],
  h3Footfall: [
    {
      hexId: '8861892e9bfffff',
      h3Resolution: 8,
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 2,
      pingCount: 3
    },
    {
      hexId: '8861892e9dfffff',
      h3Resolution: 8,
      trafficDateLocal: '2026-09-22',
      hourLocal: 18,
      uniqueVisitors: 1,
      pingCount: 1
    }
  ]
};

describe('buildKeplerDatasets', () => {
  it('creates stores, an overlap link, catchment hours, and citywide H3 cells', () => {
    const datasets = buildKeplerDatasets(snapshot, flow);

    expect(datasets.map((dataset) => dataset.info.id)).toEqual([
      STORES_DATASET_ID,
      FLOWS_DATASET_ID,
      HOURLY_FOOTFALL_DATASET_ID,
      H3_FOOTFALL_DATASET_ID
    ]);
    expect(datasets[0].data.rows).toHaveLength(2);
    expect(datasets[1].info.label).toContain('not observed paths');
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
    expect(datasets[2].data.rows).toEqual([
      ['store_a', 'Store A', 'existing', 12.9756, 77.6066, '2026-09-22', 8, 10, 11],
      ['store_b', 'Store B', 'proposed', 12.9719, 77.607, '2026-09-22', 8, 4, 4],
      ['store_a', 'Store A', 'existing', 12.9756, 77.6066, '2026-09-22', 18, 3, 3]
    ]);
    expect(datasets[3].info.label).toContain('not store visits');
    expect(datasets[3].data.rows).toEqual([
      ['8861892e9bfffff', 8, '2026-09-22', 8, 2, 3],
      ['8861892e9dfffff', 8, '2026-09-22', 18, 1, 1]
    ]);
  });

  it('uses coordinate field names that Kepler.gl can detect', () => {
    const datasets = buildKeplerDatasets(snapshot, flow);
    const flowFields = datasets[1].data.fields.map((field) => field.name);
    const hourlyFields = datasets[2].data.fields.map((field) => field.name);
    const h3Fields = datasets[3].data.fields;

    expect(flowFields).toEqual(
      expect.arrayContaining([
        'origin_latitude',
        'origin_longitude',
        'destination_latitude',
        'destination_longitude',
        'traffic_date_local'
      ])
    );
    expect(hourlyFields).toEqual(
      expect.arrayContaining(['latitude', 'longitude', 'hour_local', 'unique_visitors'])
    );
    expect(h3Fields[0]).toMatchObject({name: 'hex_id', type: 'h3'});
    expect(h3Fields.map((field) => field.name)).not.toContain('device_id');
  });

  it('filters other stores and dates without manufacturing missing-hour rows', () => {
    const extended: DashboardSnapshot = {
      ...snapshot,
      stores: [
        ...snapshot.stores,
        {...snapshot.stores[0], storeId: 'store_c', storeName: 'Store C'}
      ],
      flows: [...snapshot.flows, {...flow, scenarioId: 'other-day', trafficDateLocal: '2026-09-23'}],
      hourlyFootfall: [
        ...snapshot.hourlyFootfall,
        {storeId: 'store_c', trafficDateLocal: '2026-09-22', hourLocal: 8, uniqueVisitors: 2, pingCount: 3},
        {storeId: 'store_a', trafficDateLocal: '2026-09-23', hourLocal: 8, uniqueVisitors: 1, pingCount: 1}
      ],
      h3Footfall: [
        ...snapshot.h3Footfall!,
        {hexId: '8861892e9bfffff', h3Resolution: 8, trafficDateLocal: '2026-09-23', hourLocal: 8, uniqueVisitors: 1, pingCount: 1}
      ]
    };
    const rows = buildKeplerDatasets(extended, flow)[2].data.rows;

    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row[0])).toEqual(['store_a', 'store_b', 'store_a']);
    expect(rows.map((row) => row[6])).toEqual([8, 8, 18]);
    expect(buildKeplerDatasets(extended, flow)[3].data.rows).toHaveLength(2);
  });

  it('switches to the Store C scenario without retaining Store B map rows', () => {
    const alternateFlow: CannibalizationFlow = {
      ...flow,
      scenarioId: 'store-a-store-c',
      candidateStoreId: 'store_c',
      candidateStoreUniqueVisitors: 4,
      sharedVisitors: 0,
      orderedCandidateToExistingVisitors: 0,
      incrementalCandidateVisitors: 4,
      cannibalizationRate: 0,
      candidateOverlapRate: 0,
      candidateIncrementalReachRate: 1
    };
    const expanded: DashboardSnapshot = {
      ...snapshot,
      stores: [
        ...snapshot.stores,
        {
          storeId: 'store_c',
          storeName: 'Store C',
          status: 'candidate',
          latitude: 12.9784,
          longitude: 77.6408,
          catchmentRadiusM: 500
        }
      ],
      flows: [...snapshot.flows, alternateFlow],
      hourlyFootfall: [
        ...snapshot.hourlyFootfall,
        {storeId: 'store_c', trafficDateLocal: '2026-09-22', hourLocal: 8, uniqueVisitors: 4, pingCount: 4}
      ]
    };
    const datasets = buildKeplerDatasets(expanded, alternateFlow);

    expect(datasets[0].data.rows.map((row) => row[0])).toEqual(['store_a', 'store_c']);
    expect(datasets[1].data.rows[0]).toEqual([
      'store-a-store-c',
      'Store A',
      'Store C',
      12.9756,
      77.6066,
      12.9784,
      77.6408,
      0,
      0,
      'morning_commute',
      '2026-09-22'
    ]);
    expect(datasets[2].data.rows.map((row) => row[0])).toEqual(['store_a', 'store_a', 'store_c']);
    expect(datasets[3].data.rows).toEqual(buildKeplerDatasets(snapshot, flow)[3].data.rows);
  });

  it('emits an empty H3 dataset for a legacy snapshot without cells', () => {
    const legacy = {...snapshot, h3Footfall: undefined};
    const datasets = buildKeplerDatasets(legacy, flow);

    expect(datasets[3].info.id).toBe(H3_FOOTFALL_DATASET_ID);
    expect(datasets[3].data.rows).toEqual([]);
  });

  it('configures the hourly point radius from reported unique visitors', () => {
    const layers = KEPLER_MAP_CONFIG.visState?.layers ?? [];
    expect(layers).toHaveLength(4);
    expect(layers.find((layer) => layer.id === 'geopulse-h3-footfall-layer')).toMatchObject({
      type: 'hexagonId',
      config: {
        dataId: H3_FOOTFALL_DATASET_ID,
        columns: {hex_id: 'hex_id'},
        isVisible: true,
        visConfig: {enable3d: true}
      },
      visualChannels: {
        sizeField: {name: 'unique_visitors', type: 'integer'},
        sizeScale: 'linear'
      }
    });
    expect(layers.find((layer) => layer.id === 'geopulse-hourly-footfall-layer')).toMatchObject({
      type: 'point',
      config: {
        dataId: HOURLY_FOOTFALL_DATASET_ID,
        columns: {lat: 'latitude', lng: 'longitude'},
        isVisible: true
      },
      visualChannels: {
        sizeField: {name: 'unique_visitors', type: 'integer'},
        sizeScale: 'linear'
      }
    });
    expect(layers.find((layer) => layer.id === 'geopulse-store-reference-layer')).toMatchObject({
      type: 'point',
      config: {dataId: STORES_DATASET_ID}
    });
    expect(layers.find((layer) => layer.id === 'geopulse-store-pair-overlap-layer')).toMatchObject({
      type: 'line',
      config: {dataId: FLOWS_DATASET_ID, label: expect.stringContaining('not a travel path')}
    });
  });
});
