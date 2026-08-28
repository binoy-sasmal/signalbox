| Feed | Reqs | MB moved | Cadence p50 | 304 rate | False-200 | Entities | Persist id / sem | Ratio | entity.id | Cmp gap p50 | Header ts | Parse fail |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ovapi_tripupdates | 149 | — | — | 83.1% | 0 | 0 | — / — | — | — | — | **unknown** (none 0/5) | 0.0% |

⚠ = cadence is not a feed property. Either the header timestamp is echoed, or we sampled below Nyquist and the figure is our own polling grid. The specific reason is in `cadence.sampling` and `cadence.note` in analysis.json.
Cmp gap = wall-clock separation of the snapshots each id-stability verdict was computed from. Wider gaps are weaker evidence.

Full analysis -> runs\run2b\analysis.json

[ovapi_tripupdates] header timestamp: unknown — no test was able to discriminate
  Test A marked unavailable: content static or near-static.
