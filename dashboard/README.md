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

The dashboard deliberately does not accept Snowflake credentials. GeoPulse's scheduled
`geopulse-export-dashboard` command reads the aggregate dbt mart on the server side and writes
the same validated JSON contract to `data/output/dashboard/geopulse-dashboard.json`. A static
host can serve that file (or a copied object) at the URL configured by
`VITE_GEOPULSE_DATA_URL`. Do not make Snowflake credentials or the raw ping tables available in
the browser. See `docs/dashboard-export.md` for the publisher and recovery contract.

## Dashboard response contract

The endpoint returns one snapshot with:

- `metadata`: source relation, UTC refresh timestamp, retail timezone, and synthetic-data flag.
- `stores`: store identity, status, coordinates, and catchment radius.
- `flows`: a retail-local date/daypart comparison between an existing and candidate store,
  including unique visitors, shared visitors, incremental visitors, and three rates expressed
  from 0 to 1.

Every flow must reference stores in the same response. Visitor counts must be non-negative,
JavaScript-safe integers; shared visitors cannot exceed either store's visitors, and incremental
visitors must equal candidate visitors minus shared visitors. Each rate must agree with its
visitor counts to the dbt mart's six-decimal precision, and candidate overlap plus incremental
reach must equal 100% within that tolerance. The client rejects a snapshot that breaks these
rules instead of displaying misleading metrics.

`trafficDateLocal` and all displayed dayparts use `metadata.retailTimezone`; `refreshedAt` remains
an ISO-8601 UTC timestamp for freshness checks.

The committed sample at `public/data/geopulse-dashboard.json` is synthetic and mirrors the dbt
cannibalization fixture. Its refresh timestamp is fixed evidence,
not a claim that live data is connected. The scheduled exporter writes outside the source tree,
so deployment must copy or serve its output; it never silently replaces the committed sample.

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
