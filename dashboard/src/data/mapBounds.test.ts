import {readFileSync} from 'node:fs';

import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from './dashboardData';
import {scenarioMapBounds} from './mapBounds';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

describe('scenarioMapBounds', () => {
  it('frames the selected pair and includes the 500 m catchments', () => {
    const [bMinLng, , bMaxLng] = scenarioMapBounds(fixture, fixture.flows[0]);
    const [cMinLng, cMinLat, cMaxLng, cMaxLat] = scenarioMapBounds(fixture, fixture.flows[1]);

    expect(bMinLng).toBeLessThan(77.6066);
    expect(bMaxLng).toBeLessThan(77.62);
    expect(cMinLng).toBeLessThan(77.6066);
    expect(cMinLat).toBeLessThan(12.9756);
    expect(cMaxLng).toBeGreaterThan(77.6408);
    expect(cMaxLat).toBeGreaterThan(12.9784);
  });
});
