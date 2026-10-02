import type {addDataToMap} from '@kepler.gl/actions';

import {
  FLOWS_DATASET_ID,
  HOURLY_FOOTFALL_DATASET_ID,
  STORES_DATASET_ID
} from './keplerData';

type KeplerMapConfig = NonNullable<Parameters<typeof addDataToMap>[0]['config']>;
type ParsedKeplerMapConfig = Extract<KeplerMapConfig, {visState?: unknown}>;

export const KEPLER_MAP_CONFIG: ParsedKeplerMapConfig = {
  visState: {
    filters: [],
    layers: [
      {
        id: 'geopulse-store-reference-layer',
        type: 'point',
        config: {
          dataId: STORES_DATASET_ID,
          label: 'Store reference locations',
          color: [210, 228, 220],
          columns: {lat: 'store_latitude', lng: 'store_longitude'},
          isVisible: true,
          visConfig: {radius: 5, fixedRadius: true, opacity: 0.85, outline: false}
        },
        visualChannels: {colorField: null, sizeField: null}
      },
      {
        id: 'geopulse-store-pair-overlap-layer',
        type: 'line',
        config: {
          dataId: FLOWS_DATASET_ID,
          label: 'Store-pair overlap reference (not a travel path)',
          color: [118, 161, 177],
          columns: {
            lat0: 'origin_latitude',
            lng0: 'origin_longitude',
            lat1: 'destination_latitude',
            lng1: 'destination_longitude'
          },
          isVisible: true,
          visConfig: {opacity: 0.5, thickness: 2}
        },
        visualChannels: {colorField: null, sizeField: null}
      },
      {
        id: 'geopulse-hourly-footfall-layer',
        type: 'point',
        config: {
          dataId: HOURLY_FOOTFALL_DATASET_ID,
          label: 'Reported hourly catchment visitors',
          color: [58, 221, 153],
          columns: {lat: 'latitude', lng: 'longitude'},
          isVisible: true,
          visConfig: {
            radius: 10,
            fixedRadius: false,
            opacity: 0.85,
            outline: true,
            thickness: 1,
            radiusRange: [8, 40]
          }
        },
        visualChannels: {
          colorField: null,
          sizeField: {name: 'unique_visitors', type: 'integer'},
          sizeScale: 'linear'
        }
      }
    ]
  },
  mapState: {
    bearing: 0,
    dragRotate: false,
    latitude: 12.9738,
    longitude: 77.6068,
    pitch: 42,
    zoom: 13.2,
    isSplit: false
  },
  mapStyle: {
    styleType: 'dark',
    visibleLayerGroups: {
      label: true,
      road: true,
      border: false,
      building: true,
      water: true,
      land: true,
      '3d building': false
    }
  }
};

export const KEPLER_THEME = {
  sidePanelBg: '#101a1f',
  sidePanelHeaderBg: '#132329',
  panelBackground: '#101a1f',
  titleTextColor: '#f4f7f5',
  subtextColor: '#9eb0a7',
  subtextColorActive: '#72e6af',
  primaryBtnBgd: '#2fce8d',
  primaryBtnActBgd: '#57e4a8'
};
