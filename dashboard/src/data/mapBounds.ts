import {findStore} from './dashboardData';
import type {CannibalizationFlow, DashboardSnapshot, StoreMetric} from './types';

const METRES_PER_LATITUDE_DEGREE = 111_320;
const CATCHMENT_PADDING = 1.25;

/** Bounds include both store centers and their approximate catchment extents. */
export function scenarioMapBounds(
  snapshot: DashboardSnapshot,
  flow: CannibalizationFlow
): [number, number, number, number] {
  const stores: StoreMetric[] = [
    findStore(snapshot, flow.existingStoreId),
    findStore(snapshot, flow.candidateStoreId)
  ];
  const extents = stores.map((store) => {
    const latitudePadding = (store.catchmentRadiusM / METRES_PER_LATITUDE_DEGREE) * CATCHMENT_PADDING;
    const longitudePadding =
      latitudePadding / Math.max(Math.cos((store.latitude * Math.PI) / 180), 0.01);
    return {
      minLongitude: store.longitude - longitudePadding,
      minLatitude: store.latitude - latitudePadding,
      maxLongitude: store.longitude + longitudePadding,
      maxLatitude: store.latitude + latitudePadding
    };
  });

  return [
    Math.min(...extents.map((extent) => extent.minLongitude)),
    Math.min(...extents.map((extent) => extent.minLatitude)),
    Math.max(...extents.map((extent) => extent.maxLongitude)),
    Math.max(...extents.map((extent) => extent.maxLatitude))
  ];
}
