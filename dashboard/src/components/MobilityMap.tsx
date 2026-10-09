import {addDataToMap, createOrUpdateFilter, fitBounds, wrapTo} from '@kepler.gl/actions';
import KeplerGl from '@kepler.gl/components';
import {useEffect, useMemo, useRef} from 'react';
import {useDispatch, useSelector} from 'react-redux';

import type {AppDispatch, RootState} from '../app/store';
import {
  buildKeplerDatasets,
  H3_FOOTFALL_DATASET_ID,
  HOURLY_FOOTFALL_DATASET_ID
} from '../data/keplerData';
import {KEPLER_MAP_CONFIG, KEPLER_THEME} from '../data/keplerConfig';
import {scenarioMapBounds} from '../data/mapBounds';
import type {CannibalizationFlow, DashboardSnapshot} from '../data/types';
import {useElementSize} from '../hooks/useElementSize';
import {MobilityMapHeader} from './MobilityMapHeader';

const MAP_ID = 'geopulse-mobility-map';
const HOUR_FILTER_ID = 'geopulse-selected-hour';
const H3_HOUR_FILTER_ID = 'geopulse-selected-h3-hour';

interface MobilityMapProps {
  snapshot: DashboardSnapshot;
  flow: CannibalizationFlow;
  selectedHour: number;
}

export function MobilityMap({snapshot, flow, selectedHour}: MobilityMapProps) {
  const dispatch = useDispatch<AppDispatch>();
  const mapReady = useSelector((state: RootState) => Boolean(state.keplerGl[MAP_ID]));
  // addDataToMap starts asynchronous dataset creation; the Kepler instance can exist
  // before its hourly table is available to a filter action.
  const hourlyDataset = useSelector(
    (state: RootState) => state.keplerGl[MAP_ID]?.visState?.datasets?.[HOURLY_FOOTFALL_DATASET_ID]
  );
  const h3Dataset = useSelector(
    (state: RootState) => state.keplerGl[MAP_ID]?.visState?.datasets?.[H3_FOOTFALL_DATASET_ID]
  );
  const hasLoadedDatasets = useRef(false);
  const lastFramedScenarioId = useRef<string | null>(null);
  const {elementRef, width, height} = useElementSize<HTMLDivElement>();
  const datasets = useMemo(() => buildKeplerDatasets(snapshot, flow), [snapshot, flow]);
  const h3RowCount = datasets.find((dataset) => dataset.info.id === H3_FOOTFALL_DATASET_ID)?.data.rows.length ?? 0;
  const mapboxToken = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN || '';

  useEffect(() => {
    if (!mapReady) {
      return;
    }

    const isInitialLoad = !hasLoadedDatasets.current;
    dispatch(
      wrapTo(
        MAP_ID,
        addDataToMap({
          datasets,
          options: {
            centerMap: false,
            readOnly: false,
            keepExistingConfig: !isInitialLoad
          },
          ...(isInitialLoad ? {config: KEPLER_MAP_CONFIG} : {})
        })
      )
    );
    hasLoadedDatasets.current = true;
  }, [datasets, dispatch, mapReady]);

  useEffect(() => {
    if (
      !mapReady ||
      !hourlyDataset ||
      width === 0 ||
      height === 0 ||
      lastFramedScenarioId.current === flow.scenarioId
    ) {
      return;
    }

    // Explicit bounds frame the newly selected pair; hour scrubbing never moves the map.
    lastFramedScenarioId.current = flow.scenarioId;
    dispatch(wrapTo(MAP_ID, fitBounds(scenarioMapBounds(snapshot, flow))));
  }, [dispatch, flow, height, hourlyDataset, mapReady, snapshot, width]);

  useEffect(() => {
    if (!mapReady || !hasLoadedDatasets.current) {
      return;
    }

    const hasHourlyRows = datasets.some(
      (dataset) => dataset.info.id === HOURLY_FOOTFALL_DATASET_ID && dataset.data.rows.length > 0
    );
    if (hourlyDataset && hasHourlyRows) {
      dispatch(
        wrapTo(
          MAP_ID,
          createOrUpdateFilter(
            HOUR_FILTER_ID,
            HOURLY_FOOTFALL_DATASET_ID,
            'hour_local',
            [selectedHour, selectedHour]
          )
        )
      );
    }

    if (h3Dataset && h3RowCount > 0) {
      dispatch(
        wrapTo(
          MAP_ID,
          createOrUpdateFilter(
            H3_HOUR_FILTER_ID,
            H3_FOOTFALL_DATASET_ID,
            'hour_local',
            [selectedHour, selectedHour]
          )
        )
      );
    }
  }, [datasets, dispatch, h3Dataset, h3RowCount, hourlyDataset, mapReady, selectedHour]);

  return (
    <section className="map-card" aria-labelledby="map-heading">
      <MobilityMapHeader showH3={h3RowCount > 0} />

      <div className="map-viewport" ref={elementRef}>
        {width > 0 && height > 0 ? (
          <KeplerGl
            id={MAP_ID}
            width={width}
            height={height}
            appName="GeoPulse"
            version="Week 4"
            mapboxApiAccessToken={mapboxToken}
            theme={KEPLER_THEME}
          />
        ) : null}
      </div>
    </section>
  );
}
