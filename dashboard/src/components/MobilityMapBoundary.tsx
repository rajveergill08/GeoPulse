import 'maplibre-gl/dist/maplibre-gl.css';
import 'mapbox-gl/dist/mapbox-gl.css';

import {Provider} from 'react-redux';

import {store} from '../app/store';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {MobilityMap} from './MobilityMap';

interface MobilityMapBoundaryProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
}

export function MobilityMapBoundary({snapshot, flow}: MobilityMapBoundaryProps) {
  return (
    <Provider store={store}>
      <MobilityMap snapshot={snapshot} flow={flow} />
    </Provider>
  );
}
