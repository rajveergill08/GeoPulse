# Store cannibalization model

The Week 3 dbt layer compares anonymized devices observed around an existing store with devices
observed around a proposed or candidate store. It produces decision-ready overlap metrics by
retail-local date and traffic daypart while keeping device identifiers out of the final mart.

## Lineage and grain

```text
stg_ping_store_matches
  -> int_store_device_daypart_visits
  -> int_store_pair_daypart_overlap
  -> fct_store_cannibalization

stg_ping_store_matches + int_store_device_daypart_visits
  -> int_store_pair_ordered_evidence
  -> int_store_pair_daypart_overlap
```

The final grain is one row per
`(existing_store_id, candidate_store_id, traffic_date_local, daypart)`. Only pairs with observed
traffic at both locations during the same date and daypart are emitted. Repeated pings from the
same device inside one store catchment collapse to a single visit before overlap is calculated.

`traffic_date_local` and `daypart` use the configurable `geopulse_retail_timezone` value. The
default is `Asia/Kolkata`, while canonical source and audit timestamps remain UTC.

## KPI framework

| Metric | Calculation | Decision use |
| --- | --- | --- |
| `shared_visitors` | Distinct devices observed at both stores in the same date/daypart, even if one ping matched both catchments | Overlap volume, not a travel direction |
| `ordered_candidate_to_existing_visitors` | Distinct shared devices with at least one candidate-only ping strictly before a later existing-only ping in the same date/daypart | Supporting evidence of an observed order, not a route or a lost sale |
| `cannibalization_rate` | Shared visitors / existing-store unique visitors | Existing traffic potentially at risk |
| `candidate_overlap_rate` | Shared visitors / candidate-store unique visitors | How much candidate demand duplicates existing reach |
| `candidate_incremental_reach_rate` | Candidate-only visitors / candidate-store unique visitors | Guardrail showing potential new reach |

The CI fixture models the project scenario directly: Store A has 10 morning visitors, Store B has
4, and 3 are seen in both catchments. The resulting cannibalization rate is `3 / 10 = 0.30`, while
Store B's overlap rate is `3 / 4 = 0.75` and its incremental reach rate is `1 / 4 = 0.25`. All
three shared visitors in this fixture come from pings matched to both catchments at the same
timestamp, so the fixture has **zero** ordered candidate-to-existing visitors. The 30% overlap
must not be described as 30% of people intercepted on their way to Store A.

## Interpretation guardrails

`cannibalization_rate` is a traffic-at-risk proxy, not a causal estimate of lost sales. A GPS
observation inside both 500-metre catchments does not prove a store visit, purchase, or diversion
caused by opening the candidate. Before using a decision threshold, calibrate the metric against
store transactions, conversion rates, weekday coverage, and pre/post-opening
outcomes.

The ordered count is a stricter diagnostic: the candidate observation must not simultaneously
match the existing catchment, and the later existing observation must not simultaneously match
the candidate catchment. It stays within one retail-local date and daypart and cannot exceed
`shared_visitors`. It still does not reconstruct a continuous path or establish that opening a
new store would divert a customer. A device can traverse both areas for unrelated reasons, and
zero ordered evidence may simply reflect sparse GPS sampling rather than no real-world movement.
The dashboard's current snapshot continues to show the overlap KPIs; this new diagnostic is
available in the dbt mart and is not yet a displayed route or hourly dashboard metric.

Device-level processing in the intermediate models exists only to calculate overlap and ordering.
Production roles should restrict it, apply an approved retention period, and expose only
aggregated marts to the dashboard.

## Validation

Run the complete fixture build:

```powershell
dbt seed --profiles-dir profiles/ci --target ci --full-refresh
dbt build --profiles-dir profiles/ci --target ci --exclude-resource-type seed
```

The suite verifies daypart deduplication, shared-device counting, ordered versus simultaneous
observations, zero-overlap pairs, exact 30% fixture output, unique model grains, and rates
constrained to the inclusive `[0, 1]` range.
