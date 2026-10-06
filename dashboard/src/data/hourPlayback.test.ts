import {describe, expect, it} from 'vitest';

import {nextHour} from './hourPlayback';

describe('nextHour', () => {
  it('advances through retail-local hours and wraps after 23:00', () => {
    expect(nextHour(0)).toBe(1);
    expect(nextHour(8)).toBe(9);
    expect(nextHour(22)).toBe(23);
    expect(nextHour(23)).toBe(0);
  });
});
