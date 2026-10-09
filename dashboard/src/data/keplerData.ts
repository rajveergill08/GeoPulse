import {findStore} from './dashboardData';
import type {CannibalizationFlow, DashboardSnapshot} from './types';

export const STORES_DATASET_ID = 'geopulse_stores';
export const FLOWS_DATASET_ID = 'geopulse_flows';
export const HOURLY_FOOTFALL_DATASET_ID = 'geopulse_hourly_footfall';
export const H3_FOOTFALL_DATASET_ID = 'geopulse_h3_footfall';

interface KeplerField {
  name: string;
  type: 'string' | 'real' | 'integer' | 'h3';
  format: string;
}

interface KeplerDataset {
  info: {
    id: string;
    label: string;
  };
  data: {
    fields: KeplerField[];
    rows: Array<Array<string | number>>;
  };
}

export function buildKeplerDatasets(
  snapshot: DashboardSnapshot,
  flow: CannibalizationFlow
): KeplerDataset[] {
  const existingStore = findStore(snapshot, flow.existingStoreId);
  const candidateStore = findStore(snapshot, flow.candidateStoreId);
  const selectedStores = [existingStore, candidateStore];
  const storesById = new Map(selectedStores.map((store) => [store.storeId, store]));
  const hourlyRows = snapshot.hourlyFootfall.filter(
    (row) =>
      storesById.has(row.storeId) &&
      row.trafficDateLocal === flow.trafficDateLocal
  );
  // The H3 mart covers all pings in the city, not only matches to these stores.
  // Keep it independent of the selected pair while following its local date.
  const h3Rows = (snapshot.h3Footfall ?? []).filter(
    (row) => row.trafficDateLocal === flow.trafficDateLocal
  );

  return [
    {
      info: {
        id: STORES_DATASET_ID,
        label: 'Store locations'
      },
      data: {
        fields: [
          {name: 'store_id', type: 'string', format: ''},
          {name: 'store_name', type: 'string', format: ''},
          {name: 'store_status', type: 'string', format: ''},
          {name: 'store_latitude', type: 'real', format: ''},
          {name: 'store_longitude', type: 'real', format: ''},
          {name: 'catchment_radius_m', type: 'integer', format: ''}
        ],
        rows: selectedStores.map((store) => [
          store.storeId,
          store.storeName,
          store.status,
          store.latitude,
          store.longitude,
          store.catchmentRadiusM
        ])
      }
    },
    {
      info: {
        id: FLOWS_DATASET_ID,
        label: 'Store-pair visitor overlap (not observed paths)'
      },
      data: {
        fields: [
          {name: 'scenario_id', type: 'string', format: ''},
          {name: 'existing_store', type: 'string', format: ''},
          {name: 'candidate_store', type: 'string', format: ''},
          {name: 'origin_latitude', type: 'real', format: ''},
          {name: 'origin_longitude', type: 'real', format: ''},
          {name: 'destination_latitude', type: 'real', format: ''},
          {name: 'destination_longitude', type: 'real', format: ''},
          {name: 'shared_visitors', type: 'integer', format: ''},
          {name: 'cannibalization_rate', type: 'real', format: ''},
          {name: 'daypart', type: 'string', format: ''},
          {name: 'traffic_date_local', type: 'string', format: ''}
        ],
        rows: [
          [
            flow.scenarioId,
            existingStore.storeName,
            candidateStore.storeName,
            existingStore.latitude,
            existingStore.longitude,
            candidateStore.latitude,
            candidateStore.longitude,
            flow.sharedVisitors,
            flow.cannibalizationRate,
            flow.daypart,
            flow.trafficDateLocal
          ]
        ]
      }
    },
    {
      info: {
        id: HOURLY_FOOTFALL_DATASET_ID,
        label: 'Reported hourly catchment visitors'
      },
      data: {
        fields: [
          {name: 'store_id', type: 'string', format: ''},
          {name: 'store_name', type: 'string', format: ''},
          {name: 'store_status', type: 'string', format: ''},
          {name: 'latitude', type: 'real', format: ''},
          {name: 'longitude', type: 'real', format: ''},
          {name: 'traffic_date_local', type: 'string', format: ''},
          {name: 'hour_local', type: 'integer', format: ''},
          {name: 'unique_visitors', type: 'integer', format: ''},
          {name: 'ping_count', type: 'integer', format: ''}
        ],
        rows: hourlyRows.map((row) => {
          const store = storesById.get(row.storeId)!;
          return [
            row.storeId,
            store.storeName,
            store.status,
            store.latitude,
            store.longitude,
            row.trafficDateLocal,
            row.hourLocal,
            row.uniqueVisitors,
            row.pingCount
          ];
        })
      }
    },
    {
      info: {
        id: H3_FOOTFALL_DATASET_ID,
        label: 'Citywide H3 hourly visitors (not store visits)'
      },
      data: {
        fields: [
          {name: 'hex_id', type: 'h3', format: ''},
          {name: 'h3_resolution', type: 'integer', format: ''},
          {name: 'traffic_date_local', type: 'string', format: ''},
          {name: 'hour_local', type: 'integer', format: ''},
          {name: 'unique_visitors', type: 'integer', format: ''},
          {name: 'ping_count', type: 'integer', format: ''}
        ],
        rows: h3Rows.map((row) => [
          row.hexId,
          row.h3Resolution,
          row.trafficDateLocal,
          row.hourLocal,
          row.uniqueVisitors,
          row.pingCount
        ])
      }
    }
  ];
}
