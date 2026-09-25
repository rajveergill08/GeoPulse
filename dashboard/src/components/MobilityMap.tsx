import {addDataToMap, wrapTo} from '@kepler.gl/actions';
import KeplerGl from '@kepler.gl/components';
import {useEffect, useMemo} from 'react';
import {useDispatch, useSelector} from 'react-redux';

import type {AppDispatch, RootState} from '../app/store';
import {buildKeplerDatasets} from '../data/keplerData';
import {KEPLER_MAP_CONFIG, KEPLER_THEME} from '../data/keplerConfig';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {useElementSize} from '../hooks/useElementSize';
import {MobilityMapHeader} from './MobilityMapHeader';

const MAP_ID = 'geopulse-mobility-map';

interface MobilityMapProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
}

export function MobilityMap({snapshot, flow}: MobilityMapProps) {
  const dispatch = useDispatch<AppDispatch>();
  const mapReady = useSelector((state: RootState) => Boolean(state.keplerGl[MAP_ID]));
  const {elementRef, width, height} = useElementSize<HTMLDivElement>();
  const datasets = useMemo(() => buildKeplerDatasets(snapshot, flow), [snapshot, flow]);
  const mapboxToken = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN || '';

  useEffect(() => {
    if (!mapReady) {
      return;
    }

    dispatch(
      wrapTo(
        MAP_ID,
        addDataToMap({
          datasets,
          options: {
            centerMap: true,
            readOnly: false
          },
          config: KEPLER_MAP_CONFIG
        })
      )
    );
  }, [datasets, dispatch, mapReady]);

  return (
    <section className="map-card" aria-labelledby="map-heading">
      <MobilityMapHeader />

      <div className="map-viewport" ref={elementRef}>
        {width > 0 && height > 0 ? (
          <KeplerGl
            id={MAP_ID}
            width={width}
            height={height}
            appName="GeoPulse"
            version="Week 3"
            mapboxApiAccessToken={mapboxToken}
            theme={KEPLER_THEME}
          />
        ) : null}
      </div>
    </section>
  );
}
