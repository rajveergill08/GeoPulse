import {readFileSync} from 'node:fs';

import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from '../data/dashboardData';
import {MobilityMapErrorBoundary} from './MobilityMapErrorBoundary';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

describe('MobilityMapErrorBoundary', () => {
  it('keeps the comparison available when map rendering fails', () => {
    const boundary = new MobilityMapErrorBoundary({
      snapshot: fixture,
      flow: fixture.flows[0],
      selectedHour: 8,
      isPlaying: false,
      children: <p>Interactive map</p>
    });

    expect(renderToStaticMarkup(boundary.render())).toContain('Interactive map');

    boundary.state = MobilityMapErrorBoundary.getDerivedStateFromError();
    const fallback = renderToStaticMarkup(boundary.render());
    expect(fallback).toContain('Schematic comparison');
    expect(fallback).toContain('H3 cells are unavailable here');
    expect(fallback).not.toContain('VITE_MAPBOX_ACCESS_TOKEN');
  });
});
