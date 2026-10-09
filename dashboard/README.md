# GeoPulse mobility dashboard

This React dashboard turns the aggregated GeoPulse cannibalization mart into a location-decision
view for retail real-estate teams. It presents traffic at risk, shared visitors, candidate overlap,
incremental reach, a separate ordered-observation diagnostic, and retail-local hourly footfall.
The map's store-pair link depicts the comparison relationship, not an observed commuter route.
The candidate comparison shows only flows against the same existing store, retail-local date,
and daypart; selecting a candidate updates the KPIs, hourly footfall, and map together. It does
not rank or recommend locations.

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
the browser. The current exporter is synthetic-only; real mobility publication remains blocked
until a reviewed privacy policy exists. See `docs/dashboard-export.md` for the publisher and
recovery contract.

## Dashboard response contract

The endpoint returns one snapshot with:

- `metadata`: source description, UTC refresh timestamp, retail timezone, and synthetic-data flag.
- `stores`: store identity, status, coordinates, and catchment radius.
- `flows`: a retail-local date/daypart comparison between an existing and candidate store,
  including unique visitors, shared visitors, ordered candidate-to-existing visitors,
  incremental visitors, and three rates expressed from 0 to 1.
- `hourlyFootfall`: reported store-hour observations with local hour (0–23), distinct visitors
  in that hour, and ping count. Missing store-hours are not silently treated as zero.
- `h3Footfall` (optional for older snapshots): citywide, resolution-8 H3 cell-hour aggregates
  with `hexId`, `h3Resolution`, `trafficDateLocal`, `hourLocal`, `uniqueVisitors`, and
  `pingCount`. These are derived from GPS pings, not assigned to stores or observed paths.

Every flow must reference stores in the same response. Visitor counts must be non-negative,
JavaScript-safe integers; shared visitors cannot exceed either store's visitors, and incremental
visitors must equal candidate visitors minus shared visitors. Ordered visitors must be between
zero and shared visitors. Each rate must agree with its visitor counts to the dbt mart's
six-decimal precision, and candidate overlap plus incremental
reach must equal 100% within that tolerance. The client rejects a snapshot that breaks these
rules instead of displaying misleading metrics.
When H3 rows are present, the client also checks their canonical lowercase resolution-8
identifiers, dates, hours, nonzero safe-integer counts, unique cell/date/hour grain, and
absence of extra fields such as device identifiers. H3 rows must belong to a date used by
a scenario, but they are not filtered to a selected store pair.

The ordered count requires a candidate-only GPS match strictly before a separate
existing-only match in the same local date/daypart. Simultaneous matches to both catchments do
not count. It is observational evidence, not a measured route, intercepted sale, or hourly rate;
zero can also reflect sparse GPS sampling. The synthetic sample has three shared visitors but
zero ordered visitors.

`trafficDateLocal`, the 24-hour scrubber, and all displayed dayparts use
`metadata.retailTimezone`; `refreshedAt` remains an ISO-8601 UTC timestamp for freshness checks.
Hourly unique-visitor counts cannot be summed into daily unique reach, because one device can
appear in several hours. H3 cell-hour visitors likewise cannot be summed across cells or hours
into unique reach: a device may appear in multiple cells or hours. The selected hour changes
both the reported store catchment points and citywide H3 cells, not the
daypart-level cannibalization denominator. The user-started Play control steps through all 24
local hours, wraps from 23:00 to 00:00, and can be paused. Manual scrubbing, switching candidates,
or hiding the browser tab pauses playback. Playback is unavailable when the device requests
reduced motion, but manual scrubbing remains available. The committed synthetic fixture reports
only 08:00 observations for all three stores and an 18:00 observation for Store A; other hours
remain "No reported data," not zero or interpolated traffic. The synthetic fixture includes
citywide H3 observations at 08:00, 18:00, and 23:00. With a Mapbox token, Kepler.gl renders
those real H3 cell identifiers as extruded 3D columns scaled by hourly distinct visitors.
This is a citywide mobility-density layer, not catchment traffic, a measured route, or a
prediction of store sales. It shows no cells for hours without reported H3 data.

The committed sample at `public/data/geopulse-dashboard.json` is synthetic and mirrors the dbt
cannibalization fixture: Store B has 3 of 10 overlapping existing visitors (30%), while
Store C has 0 of 10 observed overlap and 4 of 4 candidate-only visitors in the same morning
window. Zero observed overlap is not proof of no movement or sales impact. The no-token map
preview is schematic and not to scale; it does not render H3 cells. The interactive map frames
each selected store pair and overlays the same citywide H3 observations for either candidate.
Its refresh timestamp is fixed evidence,
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
