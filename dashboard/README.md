# GeoPulse mobility dashboard

This React dashboard turns the aggregated GeoPulse cannibalization mart into a location-decision
view for retail real-estate teams. It presents traffic at risk, shared visitors, candidate overlap,
incremental reach, store catchments, and an origin-to-destination mobility arc.

## Run locally

Requirements: Node.js 20.19 or newer.

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

Add a Mapbox access token to `.env.local` to display the basemap:

```dotenv
VITE_MAPBOX_ACCESS_TOKEN=your_token
VITE_GEOPULSE_DATA_URL=/data/geopulse-dashboard.json
```

The dashboard deliberately does not accept Snowflake credentials. In production,
`VITE_GEOPULSE_DATA_URL` should point to a read-only API or exported object that returns only the
aggregated fields required by this interface.

## Dashboard response contract

The endpoint returns one snapshot with:

- `metadata`: source relation, UTC refresh timestamp, timezone, and synthetic-data flag.
- `stores`: store identity, status, coordinates, and catchment radius.
- `flows`: a date/daypart comparison between an existing and candidate store, including unique
  visitors, shared visitors, incremental visitors, and three rates expressed from 0 to 1.

Every flow must reference stores in the same response. Shared visitors cannot exceed either
store's visitors, incremental visitors must equal candidate visitors minus shared visitors, and
candidate overlap plus incremental reach must equal 100%. The client rejects a snapshot that
breaks these rules instead of displaying misleading metrics.

The committed sample at `public/data/geopulse-dashboard.json` is synthetic and mirrors the dbt
fixture in `GEOPULSE.ANALYTICS.FCT_STORE_CANNIBALIZATION`. Its refresh timestamp is fixed evidence,
not a claim that live data is connected.

## Quality checks

```powershell
npm run lint
npm run test
npm run typecheck
npm run audit:critical
npm run build
```

Kepler.gl is pinned to the stable 3.2.6 release line, with MapLibre resolved to its audited current
release. The map renderer is lazy-loaded so the decision summary can render before the larger
geospatial bundle is requested.
