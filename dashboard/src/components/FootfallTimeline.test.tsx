import {readFileSync} from 'node:fs';

import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import {parseDashboardSnapshot} from '../data/dashboardData';
import {FootfallTimeline} from './FootfallTimeline';

const fixtureUrl = new URL('../../public/data/geopulse-dashboard.json', import.meta.url);
const fixture = parseDashboardSnapshot(JSON.parse(readFileSync(fixtureUrl, 'utf8')) as unknown);
const flow = fixture.flows[0];

function renderTimeline(selectedHour: number, isPlaying = false, playbackDisabled = false) {
  return renderToStaticMarkup(
    <FootfallTimeline
      snapshot={fixture}
      flow={flow}
      selectedHour={selectedHour}
      onHourChange={() => {}}
      isPlaying={isPlaying}
      playbackDisabled={playbackDisabled}
      onPlaybackToggle={() => {}}
    />
  );
}

describe('FootfallTimeline', () => {
  it('renders a paused Play control and a keyboard-operable 24-hour range', () => {
    const html = renderTimeline(8);

    expect(html).toContain('Play 24 hours');
    expect(html).toContain('type="button"');
    expect(html).toContain('type="range"');
    expect(html).toContain('aria-valuetext="08:00 Asia/Kolkata"');
    expect(html).toContain('aria-live="polite"');
    expect(html).toMatch(/class="footfall-timeline__time"[^>]*aria-live="polite"/);
    expect(html).toContain('Unreported hours remain unreported');
  });

  it('does not broadcast every frame while playing or invent missing-hour counts', () => {
    const html = renderTimeline(9, true);

    expect(html).toContain('Pause playback');
    expect(html).toContain('aria-live="off"');
    expect(html).toMatch(/class="footfall-timeline__time"[^>]*aria-live="off"/);
    expect(html.match(/No reported data/g)).toHaveLength(2);
    expect(html.match(/Not reported, not zero visitors/g)).toHaveLength(2);
  });

  it('disables animation but retains manual selection for reduced motion', () => {
    const html = renderTimeline(8, false, true);

    expect(html).toContain('Play 24 hours');
    expect(html).toMatch(/class="footfall-timeline__playback"[^>]*disabled=""/);
    expect(html).toContain('You can still select any hour manually');
    expect(html).toContain('type="range"');
  });
});
