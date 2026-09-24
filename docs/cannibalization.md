# Store cannibalization model

The Week 3 dbt layer compares anonymized devices observed around an existing store with devices
observed around a proposed or candidate store. It produces decision-ready overlap metrics by UTC
date and traffic daypart while keeping device identifiers out of the final mart.

## Lineage and grain

```text
stg_ping_store_matches
  -> int_store_device_daypart_visits
  -> int_store_pair_daypart_overlap
  -> fct_store_cannibalization
```

The final grain is one row per
`(existing_store_id, candidate_store_id, traffic_date_utc, daypart)`. Only pairs with observed
traffic at both locations during the same date and daypart are emitted. Repeated pings from the
same device inside one store catchment collapse to a single visit before overlap is calculated.

## KPI framework

| Metric | Calculation | Decision use |
| --- | --- | --- |
| `shared_visitors` | Distinct devices observed at both stores in the same date/daypart | Direct overlap volume |
| `cannibalization_rate` | Shared visitors / existing-store unique visitors | Existing traffic potentially at risk |
| `candidate_overlap_rate` | Shared visitors / candidate-store unique visitors | How much candidate demand duplicates existing reach |
| `candidate_incremental_reach_rate` | Candidate-only visitors / candidate-store unique visitors | Guardrail showing potential new reach |

The CI fixture models the project scenario directly: Store A has 10 morning visitors, Store B has
4, and 3 visit both catchments. The resulting cannibalization rate is `3 / 10 = 0.30`, while Store
B's overlap rate is `3 / 4 = 0.75` and its incremental reach rate is `1 / 4 = 0.25`.

## Interpretation guardrails

`cannibalization_rate` is a traffic-at-risk proxy, not a causal estimate of lost sales. A GPS
observation inside both 500-metre catchments does not prove a store visit, purchase, or diversion
caused by opening the candidate. Before using a decision threshold, calibrate the metric against
store transactions, conversion rates, weekday coverage, local time zones, and pre/post-opening
outcomes.

The device-level intermediate model exists only to calculate overlap. Production roles should
restrict it, apply an approved retention period, and expose only aggregated marts to the dashboard.

## Validation

Run the complete fixture build:

```powershell
dbt seed --profiles-dir profiles/ci --target ci --full-refresh
dbt build --profiles-dir profiles/ci --target ci --exclude-resource-type seed
```

The suite verifies daypart deduplication, shared-device counting, zero-overlap pairs, exact 30%
fixture output, unique model grains, and rates constrained to the inclusive `[0, 1]` range.
