# Calibrate a Cheap Development Screen

Use `analyze_screening.py` when a cheaper subset, training duration, input scale, or episode horizon will decide which candidates get expensive full evaluation. It summarizes observed ranking preservation across paired valid reference measurements for any scalar task family. It does not evaluate candidates, recompute supplied scores, or establish future screen reliability.

## Prepare Paired References

Fix the screen definition and planned survivor count before measuring calibration references. Include a credible control and available materially different routes; a set of nearly identical variants may hide family-specific bias. Use existing compatible measurements when possible. Count calibration work as diagnostics; new candidate configurations are separate trials for accounting, and retain full/confirmation resources when a finite constraint requires them.

Within each stage, references must share its frozen evaluator, workload, aggregation, resource and seed protocol. Across stages, pair the same candidate identity/recipe, allowing only the declared fidelity differences. The full score must be the declared total objective, not a convenient component. Different screen/full formulas and directions are supported because the tool compares **ordering within each stage**, rather than their numerical values across stages.

Create UTF-8 CSV with unique non-empty candidate IDs and finite scores:

```csv
candidate,screen_score,full_score
baseline,10,8
route-a,9,7
route-b,11,6
```

Extra named columns can retain result paths or artifact identities; they do not affect calculation. Verify pairing, result completeness, score provenance, hard rules and development stage in the adapter before populating this table. Record references with missing/failed measurements separately; successful pairs alone cannot establish the screen's failure rate or justify discarding those routes.

```powershell
python <skill-dir>/scripts/analyze_screening.py `
  --scores <paired-development-scores.csv> `
  --screen-direction minimize --full-direction minimize `
  --keep-count 2 --output <new-screen-analysis.json>
```

Directions are required independently. Both tie epsilons default to zero; set `--screen-tie-epsilon` and `--full-tie-epsilon` in their respective score units when justified before calibration. References are not confirmation evidence; never use held-out final scores to calibrate a screen for more search.

## Use the Report for a Decision

The report preserves input/checker hashes, configuration and reference scores. It counts concordant/inverted pairs and each kind of tie separately, lists up to ten inversion examples, and shows screen survivors plus full-best candidates retained/missed under the declared tolerances. Pair agreement excludes tied comparisons and is unavailable when no decisive pair exists; a high agreement fraction can still hide the missed best candidate.

All cutoff ties survive, so `actual_keep_count` may exceed `nominal_keep_count`. Account for that full-evaluation cost; arbitrary tie breaking supplies no score evidence. An inversion or missed full-best candidate is an observed limitation to address with a better screen, broader retention or full evaluation of the affected alternatives. Revising a screen from these results requires fresh calibration references where practical; perfect fit on the same references does not establish reliability.

Keep some full evaluations on distinct mechanisms that the screen would reject. If no useful screen can be established with the available resources, use fewer credible full-fidelity trials or continue directly without a screen. Screen survivors still require matched full objective and hard checks before promotion. This diagnostic neither chooses an incumbent nor allocates a default trial quota.

Analysis succeeds with exit code 0 even when ranks invert; `status: analyzed` describes computation only. Malformed input/configuration, changed input bytes or an existing output returns code 2. Existing outputs are never overwritten. Reuse the receipt only for the same input/checker/configuration; applicability to a changed fidelity, task distribution or new family needs separate evidence.
