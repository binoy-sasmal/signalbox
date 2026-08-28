| Feed | Reqs | MB moved | Cadence p50 | 304 rate | False-200 | Entities | Persist id / sem | Ratio | entity.id | Cmp gap p50 | Header ts | Parse fail |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hsl_tripupdates | 590 | 265.6 | 15.0 s | 58.6% | 3 | 1261 | 99.2% / 100.0% | 0.99 | stable | 13 s | **generation** | 0.0% |
| hsl_vehiclepositions | 1492 | 152.4 | 2.0 s ⚠ | 0.2% | 0 | 849 | 99.9% / 99.9% | 1.00 | stable | 2 s | **unknown** | 0.0% |
| ovapi_tripupdates | 61 | 118.3 | 60.0 s ⚠ | 0.0% | 0 | 10932 | 98.3% / 98.3% | 1.00 | stable | 62 s | **generation** | 0.0% |
| vbb | 562 | 353.9 | 29.0 s | 70.0% | 0 | 8309.0 | 95.3% / 99.8% | 0.95 | stable | 25 s | **generation** | 0.0% |

⚠ = cadence is not a feed property. Either the header timestamp is echoed, or we sampled below Nyquist and the figure is our own polling grid. The specific reason is in `cadence.sampling` and `cadence.note` in analysis.json.
Cmp gap = wall-clock separation of the snapshots each id-stability verdict was computed from. Wider gaps are weaker evidence.

Full analysis -> runs\run2\analysis.json

[hsl_tripupdates] header timestamp: generation — unanimous across 2 available test(s): A_body_modulo_timestamp, E_http_date_last_modified
  churn: entity.id tracks the semantic key (ratio 0.99); it is usable as a dedup key on this feed. Raw id persistence is 99.2%, the remainder being genuine entity turnover rather than id instability.

[hsl_vehiclepositions] header timestamp: unknown — available tests disagree (A_body_modulo_timestamp=generation, B_lag_shape=generation, C_async_repoll=echo); not resolved by narrative
  churn: entity.id tracks the semantic key (ratio 1.00); it is usable as a dedup key on this feed. Raw id persistence is 99.9%, the remainder being genuine entity turnover rather than id instability.

[ovapi_tripupdates] header timestamp: generation — unanimous across 4 available test(s): A_body_modulo_timestamp, B_lag_shape, C_async_repoll, E_http_date_last_modified
  churn: entity.id tracks the semantic key (ratio 1.00); it is usable as a dedup key on this feed. Raw id persistence is 98.3%, the remainder being genuine entity turnover rather than id instability.

[vbb] header timestamp: generation — unanimous across 2 available test(s): C_async_repoll, E_http_date_last_modified
  Test A marked unavailable: content static or near-static.
  churn: entity.id tracks the semantic key (ratio 0.95); it is usable as a dedup key on this feed. Raw id persistence is 95.3%, the remainder being genuine entity turnover rather than id instability.
