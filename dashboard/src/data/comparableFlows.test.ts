import {readFileSync} from 'node:fs';

import {describe, expect, it} from 'vitest';

import {comparableFlows} from './comparableFlows';
import {parseDashboardSnapshot} from './dashboardData';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

describe('comparableFlows', () => {
  it('compares Store B and Store C only for the same existing store and local window', () => {
    expect(comparableFlows(fixture, fixture.flows[0]).map((flow) => flow.candidateStoreId)).toEqual([
      'store_b',
      'store_c'
    ]);

    const otherWindows = {
      ...fixture,
      flows: [
        ...fixture.flows,
        {...fixture.flows[1], scenarioId: 'other-date', trafficDateLocal: '2026-09-23'},
        {...fixture.flows[1], scenarioId: 'other-daypart', daypart: 'midday' as const},
        {...fixture.flows[1], scenarioId: 'other-existing', existingStoreId: 'store_b'}
      ]
    };
    expect(comparableFlows(otherWindows, fixture.flows[0])).toEqual(fixture.flows);
  });
});
