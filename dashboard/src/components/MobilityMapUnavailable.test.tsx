import {readFileSync} from 'node:fs';

import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from '../data/dashboardData';
import {MobilityMapUnavailable} from './MobilityMapUnavailable';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

describe('MobilityMapUnavailable', () => {
  it('announces a manually selected hour but not every playback frame', () => {
    const paused = renderToStaticMarkup(
      <MobilityMapUnavailable snapshot={fixture} flow={fixture.flows[0]} selectedHour={8} isPlaying={false} />
    );
    const playing = renderToStaticMarkup(
      <MobilityMapUnavailable snapshot={fixture} flow={fixture.flows[0]} selectedHour={9} isPlaying />
    );

    expect(paused).toMatch(/class="map-preview__hour-note" role="status"/);
    expect(playing).toMatch(/class="map-preview__hour-note"/);
    expect(playing).not.toMatch(/class="map-preview__hour-note" role="status"/);
    expect(playing).toContain('Hourly data reported for 0 of 2 selected stores');
  });
});
