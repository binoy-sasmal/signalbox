| Feed | Reqs | MB moved | Cadence p50 | 304 rate | False-200 | Entities | Persist id / sem | Ratio | entity.id | Cmp gap p50 | Header ts | Parse fail |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gtfs_de | 54 | 1206.5 | 30 s ⚠ | 41.5% | 0 | 163819.5 | 99.4% / 99.4% | 1.00 | stable | 30 s | **generation** | 0.0% |
| ovapi_tripupdates | 16 | 30.8 | 60 s ⚠ | 0.0% | 1 | 13834.0 | 98.9% / 98.9% | 1.00 | stable | 62 s | **generation** | 0.0% |
| vbb | 137 | 101.2 | 16.0 s | 64.0% | 0 | 9027 | 97.0% / 99.8% | 0.97 | stable | 15 s | **generation** | 0.0% |

⚠ = cadence is not a feed property. Either the header timestamp is echoed, or we sampled below Nyquist and the figure is our own polling grid. The specific reason is in `cadence.sampling` and `cadence.note` in analysis.json.
Cmp gap = wall-clock separation of the snapshots each id-stability verdict was computed from. Wider gaps are weaker evidence.
