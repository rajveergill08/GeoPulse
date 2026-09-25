import {findStore} from './dashboardData';
import type {CannibalizationFlow, DashboardSnapshot} from './types';

export const STORES_DATASET_ID = 'geopulse_stores';
export const FLOWS_DATASET_ID = 'geopulse_flows';

interface KeplerField {
  name: string;
  type: 'string' | 'real' | 'integer';
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

  return [
    {
      info: {
        id: STORES_DATASET_ID,
        label: 'Store catchments'
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
        label: 'Shared commuter flow'
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
          {name: 'traffic_date_utc', type: 'string', format: ''}
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
            flow.trafficDateUtc
          ]
        ]
      }
    }
  ];
}
