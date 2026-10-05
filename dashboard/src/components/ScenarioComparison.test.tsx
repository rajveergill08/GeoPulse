import {readFileSync} from 'node:fs';

import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from '../data/dashboardData';
import {ScenarioComparison} from './ScenarioComparison';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);

describe('ScenarioComparison', () => {
  it('renders two accessible selectable candidates and an observational caveat', () => {
    const html = renderToStaticMarkup(
      <ScenarioComparison snapshot={fixture} selectedFlow={fixture.flows[0]} onScenarioChange={() => {}} />
    );

    expect(html.match(/<button\b/g)).toHaveLength(2);
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('Store B - Brigade Road');
    expect(html).toContain('Store C - Indiranagar');
    expect(html).toContain('30%');
    expect(html).toContain('Zero observed overlap does not prove no movement');
  });
});
