# Replay Fixed Inference Votes

Use `scripts/replay_inference_votes.py` when ordered, already generated development answers can resolve a selection or stopping question. It compares fixed-budget plurality voting with stopping when the leader cannot be caught by any remaining votes. This is a read-only cache analysis, not a generation engine, interactive simulator or official evaluator.

## Prepare the Development Cache

Supply one UTF-8 JSON object with:

- `schema_version: 1` and `stage: "development"`. Confirmation/test caches are rejected.
- `generation`: `recipe_sha256`, `workload_sha256` and `answer_parser_sha256`, each a lowercase SHA-256 identifying the actual generating recipe, workload and parser. Additional metadata can retain model, prompt, engine or source artifact identities. These are declarations; the adapter must check provenance and complete case coverage.
- `cases`: a non-empty list. Each case has a unique non-empty string `id`, a normalized string `target`, and an ordered non-empty `samples` list.
- Each sample has a case-local unique string `id`, `status` and `answer`. `completed` means an extracted non-empty string answer; `invalid`, `timeout` and `failed` require `answer: null`. Every sample consumes a slot. The array order is the fixed order used by the policy; sample IDs are not sorted or converted to numbers.
- Optional `elapsed_seconds` is a finite non-negative number, or null/omitted when unknown. It refers only to the supplied sample's recorded cost, whose measurement boundary belongs to the adapter.

The parser must already have mapped equivalent answers to the intended exact strings. The tool neither extracts answers from prose nor coerces `"001"` to `"1"`. Targets are used only after selection to calculate exact-match correctness; they never influence votes. Failed/answerless cases remain in the denominator.

Use the existing task's planned sample budget for `--max-samples`. Every case must contain at least that many recorded slots; missing slots are unknown, not failures or grounds to omit the case. Only the first N slots enter the comparison, even if the cache contains more. A new policy is a mechanism proposal, not permission for an unrequested budget/threshold sweep.

```sh
python <skill-dir>/scripts/replay_inference_votes.py \
  --trace <development-cache.json> --max-samples 5 \
  --output <new-replay-report.json>
```

## Understand the Stopping Rule

The full-budget policy selects the most frequent valid answer. Final ties use the answer first seen in the supplied order; no valid answer yields null. Invalid/failed samples cast no vote but consume their slots.

After each slot, early stopping requires:

```text
leader_count > runner_count + remaining_slots
```

The runner count is zero when only one answer has been observed. Even if all remaining slots vote for the strongest rival, they cannot tie the leader, so the full-budget answer is preserved. A majority of the votes seen so far is insufficient. With several distinct answers, an irreversible plurality can occur without an absolute majority of the full budget. This conservative rule does not stop on a tie that might later be broken by the fixed tie rule.

The tool consumes recorded slots through that stopping point, including failures. It compares exactly one full-budget policy with this rule, not a tuned family of stopping thresholds. Complexity depends on the number of recorded samples and distinct answers.

## Turn the Report into the Next Implementation

The report includes per-case answers, correctness, failure counts, used slots and optional cached costs, plus input bytes, declared generation identities, configuration and analyzer hashes. Exact-match accuracy is an unweighted development statistic; task weights, semantic correctness and other official scoring terms remain the task adapter's responsibility.

`cases_with_correct_sample` is retrospective coverage of the first N cached slots. A correct sample that loses the vote suggests a selection question; no correct sample may motivate investigation of generation, supervision, parsing or labels. Neither observation proves the cause or permits a selector to consult hidden targets. Inspect the relevant failures before choosing the mechanism.

`cached_sample_seconds` only sums supplied costs for selected slots, and remains null if any contributing cost is unknown. It does not estimate concurrent wall time, cache contention, engine changes or the cost of reallocating saved work. `skipped_sample_slots` is a counterfactual count on this cache; the analysis does not recover compute already spent producing it.

Put the report path and hash in the existing proposal's `basis`/`validation` or decision card, and cite the real development candidate in `feedback_from`. The report intentionally omits adapter-result `candidate_hash`, `valid` and `score`: do not fabricate a contender from it. To pursue the idea, implement the selected policy with its parser/tie/failure semantics, run the actual adapter under the competition limit, and archive the measured outcome through [the ordinary successor path](iteration-trace.md#attach-the-measured-outcome). Confirmation stays independent.

The CLI returns 0 for a completed analysis, even if all answers are wrong. Invalid inputs, changed source bytes or an existing output return 2. The cache is never modified and an existing report is never overwritten. Reuse a report only while its input/configuration/analyzer identities and its relevance to the task remain valid.
