import {readFileSync} from 'node:fs';

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
        orderedCandidateToExistingVisitors: 0,
        incrementalCandidateVisitors: 1,
        cannibalizationRate: 0.3,
        candidateOverlapRate: 0.75,
        candidateIncrementalReachRate: 0.25
      }
    ],
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
      }
    ]
  };
}

describe('parseDashboardSnapshot', () => {
  it('keeps both synthetic candidate scenarios at their reconciled morning counts', () => {
    const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
    const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

    expect(fixture.metadata.synthetic).toBe(true);
    expect(fixture.flows).toHaveLength(2);
    expect(fixture.flows[0]).toMatchObject({
      candidateStoreId: 'store_b',
      sharedVisitors: 3,
      cannibalizationRate: 0.3,
      orderedCandidateToExistingVisitors: 0
    });
    expect(fixture.flows[1]).toMatchObject({
      candidateStoreId: 'store_c',
      existingStoreUniqueVisitors: 10,
      candidateStoreUniqueVisitors: 4,
      sharedVisitors: 0,
      orderedCandidateToExistingVisitors: 0,
      incrementalCandidateVisitors: 4,
      cannibalizationRate: 0,
      candidateOverlapRate: 0,
      candidateIncrementalReachRate: 1
    });
    expect(fixture.hourlyFootfall).toContainEqual({
      storeId: 'store_c',
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 4,
      pingCount: 4
    });
    expect(fixture.h3Footfall).toHaveLength(6);
    expect(fixture.h3Footfall).toContainEqual({
      hexId: '8861892e9bfffff',
      h3Resolution: 8,
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 3,
      pingCount: 4
    });
  });

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

  it('requires a directional count and accepts zero as an observed result', () => {
    const valid = validSnapshot();
    expect(parseDashboardSnapshot(valid)).toEqual(valid);

    const missing = validSnapshot();
    const incompleteFlow: Partial<(typeof missing.flows)[number]> = missing.flows[0];
    delete incompleteFlow.orderedCandidateToExistingVisitors;
    expect(() => parseDashboardSnapshot(missing)).toThrow(
      'Dashboard response contains invalid cannibalization metrics.'
    );
  });

  it('rejects an invalid directional count or one exceeding shared visitors', () => {
    for (const count of [-1, 1.5, Number.MAX_SAFE_INTEGER + 1, 4]) {
      const snapshot = validSnapshot();
      snapshot.flows[0].orderedCandidateToExistingVisitors = count;
      expect(() => parseDashboardSnapshot(snapshot)).toThrow(
        'Dashboard response contains invalid cannibalization metrics.'
      );
    }

    const allShared = validSnapshot();
    allShared.flows[0].orderedCandidateToExistingVisitors = 3;
    expect(parseDashboardSnapshot(allShared)).toEqual(allShared);
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

  it('requires explicit hourly data but permits a sparse empty hour series', () => {
    const missing: Partial<DashboardSnapshot> = validSnapshot();
    delete missing.hourlyFootfall;
    expect(() => parseDashboardSnapshot(missing)).toThrow(
      'Dashboard response contains invalid hourly footfall metrics.'
    );

    const sparse = validSnapshot();
    sparse.hourlyFootfall = [];
    expect(parseDashboardSnapshot(sparse)).toEqual(sparse);
  });

  it('rejects unknown stores or a date not represented by a scenario flow', () => {
    const unknownStore = validSnapshot();
    unknownStore.hourlyFootfall[0].storeId = 'store_missing';
    expect(() => parseDashboardSnapshot(unknownStore)).toThrow(
      'Dashboard hourly footfall references an unknown store or flow date.'
    );

    const unrelatedDate = validSnapshot();
    unrelatedDate.hourlyFootfall[0].trafficDateLocal = '2026-09-23';
    expect(() => parseDashboardSnapshot(unrelatedDate)).toThrow(
      'Dashboard hourly footfall references an unknown store or flow date.'
    );
  });

  it('rejects invalid local dates and hours', () => {
    for (const localDate of ['2026-02-30', '2026-9-22', '2026-09-22T00:00:00Z']) {
      const snapshot = validSnapshot();
      snapshot.hourlyFootfall[0].trafficDateLocal = localDate;
      expect(() => parseDashboardSnapshot(snapshot)).toThrow(
        'Dashboard response contains invalid hourly footfall metrics.'
      );
    }

    for (const hour of [-1, 24, 8.5, Number.MAX_SAFE_INTEGER + 1]) {
      const snapshot = validSnapshot();
      snapshot.hourlyFootfall[0].hourLocal = hour;
      expect(() => parseDashboardSnapshot(snapshot)).toThrow(
        'Dashboard response contains invalid hourly footfall metrics.'
      );
    }
  });

  it('rejects negative, fractional, unsafe, or inconsistent hourly counts', () => {
    for (const [uniqueVisitors, pingCount] of [
      [-1, 1],
      [0.5, 1],
      [Number.MAX_SAFE_INTEGER + 1, Number.MAX_SAFE_INTEGER + 1],
      [2, 1]
    ]) {
      const snapshot = validSnapshot();
      snapshot.hourlyFootfall[0].uniqueVisitors = uniqueVisitors;
      snapshot.hourlyFootfall[0].pingCount = pingCount;
      expect(() => parseDashboardSnapshot(snapshot)).toThrow(
        'Dashboard response contains invalid hourly footfall metrics.'
      );
    }
  });

  it('rejects duplicate store-date-hour rows', () => {
    const snapshot = validSnapshot();
    snapshot.hourlyFootfall.push({...snapshot.hourlyFootfall[0]});
    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard hourly footfall contains duplicate store-hour metrics.'
    );
  });

  it('rejects unexpected fields in an hourly aggregate', () => {
    const snapshot = validSnapshot();
    const hourlyRow = snapshot.hourlyFootfall[0] as typeof snapshot.hourlyFootfall[number] & {
      deviceId?: string;
    };
    hourlyRow.deviceId = 'private-device';
    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard response contains invalid hourly footfall metrics.'
    );
  });

  it('accepts optional, empty, and valid citywide H3 aggregates', () => {
    const legacy = validSnapshot();
    expect(parseDashboardSnapshot(legacy)).toEqual(legacy);

    const snapshot = validSnapshot();
    snapshot.h3Footfall = [];
    expect(parseDashboardSnapshot(snapshot)).toEqual(snapshot);

    snapshot.h3Footfall.push({
      hexId: '8861892e9bfffff',
      h3Resolution: 8,
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 2,
      pingCount: 3
    });
    expect(parseDashboardSnapshot(snapshot)).toEqual(snapshot);
  });

  it('rejects invalid H3 identifiers, resolution, dates, hours, and counts', () => {
    const validRow = {
      hexId: '8861892e9bfffff',
      h3Resolution: 8 as const,
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 2,
      pingCount: 3
    };
    const invalidRows: unknown[] = [
      {...validRow, hexId: '8861892E9BFFFFF'},
      {...validRow, hexId: '8861892e9bffff'},
      {...validRow, h3Resolution: 7},
      {...validRow, trafficDateLocal: '2026-02-30'},
      {...validRow, hourLocal: 24},
      {...validRow, hourLocal: 8.5},
      {...validRow, uniqueVisitors: 0},
      {...validRow, uniqueVisitors: 4},
      {...validRow, pingCount: Number.MAX_SAFE_INTEGER + 1},
      {...validRow, deviceId: 'private-device'}
    ];

    for (const row of invalidRows) {
      const snapshot = {...validSnapshot(), h3Footfall: [row]};
      expect(() => parseDashboardSnapshot(snapshot)).toThrow(
        'Dashboard response contains invalid H3 footfall metrics.'
      );
    }
  });

  it('rejects duplicate H3 cell-hours and unrelated dates', () => {
    const snapshot = validSnapshot();
    snapshot.h3Footfall = [{
      hexId: '8861892e9bfffff',
      h3Resolution: 8,
      trafficDateLocal: '2026-09-22',
      hourLocal: 8,
      uniqueVisitors: 2,
      pingCount: 3
    }];
    snapshot.h3Footfall.push({...snapshot.h3Footfall[0]});
    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard H3 footfall contains duplicate hex-hour metrics.'
    );

    snapshot.h3Footfall.pop();
    snapshot.h3Footfall[0].trafficDateLocal = '2026-09-23';
    expect(() => parseDashboardSnapshot(snapshot)).toThrow(
      'Dashboard H3 footfall references an unknown flow date.'
    );
  });
});
