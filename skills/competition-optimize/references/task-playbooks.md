# Task-Family Search Guide

Read only the relevant section when choosing baselines or improvement mechanisms. These are conditional experiment choices, not fixed algorithm prescriptions or implemented adapters. For score provenance and validity requirements, use [the adapter contract](adapter-contract.md); for experiment decisions, use [the search protocol](score-search.md).

## Data and Model Competitions

For unweighted scalar regression or binary CSV predictions, [the local prediction tools](data-model.md) provide RMSE, MAE, binary log loss, ROC-AUC, matched score and row/group sampling-uncertainty comparisons, development error/slice diagnostics, and fixed-weight blending with reusable recipes. Other metrics or aggregation rules require a task-specific adapter.

Identify the statistical unit and intended test conditions before training. Determine whether samples share patients/users/devices, follow time order, or contain duplicates; choose group/time separation where appropriate. Check distribution shifts using features permitted by the rules. Keep target-dependent feature generation inside training folds.

For explicit row-ID partitions, [audit the declared split](validation-split.md) before fitting, adding group/time/label-availability metadata only when required by the task. Reuse matching receipts across candidates; they do not prove actual pipeline fitting or independence.

Inspect loader/cache preprocessing and retain fitting-row and pipeline lineage as described in [training and validation evidence](data-model.md#establish-training-and-validation-evidence). Small held-out sets can reverse model rankings; resolve close comparisons with affordable matched internal folds or seeds when that would change the next proposal. Freeze a delivery rule for confirmation disagreements rather than selecting a new rule from held-out outcomes.

Build a cheap sanity baseline and, when resources allow, a credible model from a different family suggested by task evidence. Compare the official metric from aligned validation predictions; the training loss or accuracy may not be the contest objective. Interpret model rankings jointly with feature/data quality and error regimes.

| Observation | Experiment to consider | Confirmation needed |
| --- | --- | --- |
| A simple or alternative family approaches the current model | Inspect the pipeline and propose improved representation/features or another applicable family | Same folds, official metric, and training/inference cost |
| Errors cluster by group, time, class, or input regime | Investigate split mismatch, missing signal, label noise, or weighting | Mechanism-specific ablation and evidence beyond the tested regime |
| Useful interactions or domain signals are absent | Add a targeted feature or preprocessing component | Fold-safe fitting, no target leakage, and metric gain |
| Allowed external or unlabeled data could improve coverage | Try additional data, pretraining, or soft pseudo-labels | Provenance, rule permission, and a teacher that did not train on held-out labels |
| Predictions show objective-relevant error interaction | Consider a small blend or stacking trial on cached OOF predictions; for two-parent RMSE/MAE, check convex-loss directions when useful | Case wins alone are insufficient; correct ID alignment, full objective, inference cost, and independent confirmation of the frozen ensemble |
| Training is stable but the metric depends on output interpretation | Inspect output mapping and implement a justified calibration or decoding change | Development-only selection and final confirmation under the official metric |

Use the simplest complete pipeline that tests the proposal. Inspect the current pipeline, learning behavior and historical comparisons to identify missing signal, representation limits or wasted work; implement the next supported mechanism without a default hyperparameter/seed sweep. Final retraining on all permitted labeled data must keep the selected pipeline fixed and satisfy inference limits; preserve the earlier validation evidence rather than claiming a new full-data validation score.

## LLM Generation and Agent Competitions

When the submitted system trains or runs a language model, use the relevant section of [the LLM/agent playbook](llm-agent-competitions.md). It connects validation and scoring behavior, synthetic data and teacher distillation, post-training, inference budgets, trajectory replay and deterministic agent components to the existing implementation/evaluation loop. An LLM writing a conventional contest algorithm does not by itself require this playbook.

Choose a mechanism from observed failures and the task's constraints. Preserve model/tokenizer/template and data lineage, compare the complete system under the actual inference limit, and distinguish cached-trajectory diagnostics from a new executed policy. The bundled numeric training and CSV prediction tools do not supply an LLM trainer, weight merger or interactive evaluator.

## Algorithms and Combinatorial Optimization

Distinguish constructing a solution, improving it offline, making online decisions, and accelerating an exact solver. Inspect input scale, allowed operations, and the scorer. On tiny instances, a slow exact or exhaustive reference can expose quality gaps even when it cannot serve as the submitted algorithm.

Start from a valid constructive/reference solution. Use per-instance objective components, constraint violations, search progress, representative outputs, and profiles to locate the limiting mechanism. When available, inspect the official visualizer or a trace; a final scalar alone may hide poor neighborhoods or expensive score updates.

| Observation | Experiment to consider | Confirmation needed |
| --- | --- | --- |
| Initial constructions have very different quality | Explore another construction or representation | Gains on representative full-scale cases |
| Local search stalls with substantial estimated headroom | Change neighborhoods, restarts, annealing, beam search, or decomposition as task evidence suggests | Progress curves and final score under the same runtime limit |
| Inner scoring dominates runtime | Use incremental updates, caching, or a candidate-internal approximation | Correct updates and final evaluation using the declared objective |
| Exact solver time explodes on larger instances | Change encoding, auxiliary variables, symmetry treatment, or variable order | Correctness, larger-instance scaling, success rate, and the contest objective |
| Online decisions do well on averages but fail in particular sequences | Try lookahead where allowed, a revised heuristic, or a regime policy | Only information available at decision time and matched sequence evaluation |
| Strategies excel at different sizes or structures | Combine them or use an input-based selector | Selector overhead, worst allowed resource use, and aggregate objective |

Candidate speed can buy more search iterations under the contest deadline. Measure both iteration throughput and the quality obtained within the actual runtime budget; faster operations alone do not establish a higher score. Record whether search exhausted a neighborhood or hit its work/time cap, with development objective progress when useful. A weak construction may become a stronger complete construction-plus-search pipeline; compare that mechanism before rejecting it when affordable. Keep hard time/memory checks separate from soft speed/quality tradeoffs. Confirm on fresh instances/seeds and boundary sizes, respecting the official aggregation.

## Stochastic Simulation, Control, and Interactive Tasks

Identify which state or observations are available to the candidate, which actions are permitted, and how outcomes become the score. Separate hard feasibility failures from penalties that are part of the official objective. Include per-episode query/interaction costs and execution limits.

Use a simple valid policy, matched environment seeds, and repeated policy seeds where applicable. Track return/score, failure rates, dispersion, and cost by scenario. A single lucky episode or low percentile does not establish the official objective if it aggregates outcomes differently.

| Observation | Experiment to consider | Confirmation needed |
| --- | --- | --- |
| Results vary widely between runs | Resolve uncertainty or test variance reduction | Matched comparisons and sufficient repetition for the decision |
| Failures cluster in particular states or regimes | Revise the policy, observations, or task model | Feasibility and official penalties on representative scenarios |
| Planning consumes most of the deadline | Change approximation, horizon, caching, or per-state compute allocation | Policy quality including all computation/query cost |
| Cheap short episodes rank policies inconsistently | Evaluate selected policies on full episodes | Matched horizons and the declared score aggregation |
| Different policies cover different regimes | Test a selector using allowed observations | Combined objective, selection overhead, and fresh confirmation scenarios |

Policy parameters, surrogate rewards, or internal planning heuristics are candidate changes; keep the official reward/evaluator fixed. Hidden future state or final outcome cannot be a selector feature. Confirm under the intended environment distribution and label sensitivity to alternative distributions as diagnostic evidence.
