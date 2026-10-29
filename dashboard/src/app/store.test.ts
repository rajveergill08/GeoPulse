import {deleteEntry, registerEntry} from '@kepler.gl/actions';
import {describe, expect, it} from 'vitest';

import {baseMapStyleForToken} from '../data/keplerConfig';
import {store} from './store';

describe('Kepler store', () => {
  it('starts with the selected basemap style before data is loaded', () => {
    const mapId = 'basemap-startup-test';
    store.dispatch(registerEntry({id: mapId}));

    try {
      const mapStyle = store.getState().keplerGl[mapId]?.mapStyle;
      expect(mapStyle?.styleType).toBe(
        baseMapStyleForToken(import.meta.env.VITE_MAPBOX_ACCESS_TOKEN)
      );
      expect(mapStyle?.mapStyles?.no_map?.style).toMatchObject({sources: {}, layers: []});
    } finally {
      store.dispatch(deleteEntry(mapId));
    }
  });
});
