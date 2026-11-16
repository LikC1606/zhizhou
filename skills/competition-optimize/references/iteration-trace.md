# Connect Feedback to Executed Changes

Use this when repeated trials are managed by `candidate_archive.py`. It links an agent-authored proposal to verified parent code and development feedback, then to a new adapter result. Existing equivalent ledger links are sufficient; do not migrate old trials or reconstruct proposals after seeing their results.

## Retrieve Evidence for the Next Implementation

```powershell
python <skill-dir>/scripts/candidate_archive.py brief `
  --archive <run>/candidate-archive.jsonl
```

Use this read-only view before opening more logs. It supplies one shared comparison identity, the best measured development representative, recent distinct implementations on the active route, best/latest versions of alternative routes, unresolved feedback, recent failure evidence and code/result paths. Candidate cards are included once even when several decisions reference them. Read the relevant function or pipeline at those paths, compare the mechanism with the retained failures, and choose a concrete next implementation. A successful retrieval does not complete an optimization request.

The default anchor is the latest development record. Use `--anchor <candidate-id>` to select the comparison and route for a different parent; this is not a historical cutoff. A failed latest experiment still retains the previous valid best under the same comparison. Early failures can lack metric/evaluator metadata and therefore anchor a different comparison; the unattended driver's separate recovery packet supplies verified diagnostics and a development reference without comparing their scores. `best_development` is a retrieval representative, not an incumbent promotion or a frozen finalist. Unknown scalar objectives keep their components and have no best-score ranking. Costs remain visible for the agent's investment decision.

The unattended driver also checks whether new complete contracts remain isolated with only one measured implementation. Its `comparison_recovery` can point to an earlier isolated target even when the latest record is a healthy smoke run. Retrieve the cited snapshots and establish a common legal development contract before comparing reference and candidate. A genuine new result from archived code may supply the missing comparison with `--reuse-reason`; it remains a measurement of that implementation and does not fulfill a code-change proposal. Cross-contract cards carry identities and pointers without scores or original feedback.

Scored candidate cards share the exact evaluator, workload/split, score model, evaluation configuration, stage, environment and objective metadata. Pending proposals can also cite development references under another contract: these receive separate identity/pointer cards without scores or original feedback. Confirmation records do not change this view, including selection, ordering and counts. Score ordering uses the first valid comparable observation of each **implementation identity**, so stochastic output changes and renamed routes cannot create a new best implementation. Repeated measurements stay visible as measurements; use the task's uncertainty/aggregation procedure when they matter rather than promoting the luckiest observation.

For `prediction_csv` results with a complete training-code/recipe directory, implementation identity uses that directory; prediction bytes retain a separate artifact fingerprint. An adapter can declare `candidate_scope: generated_artifact` for other produced outputs or weights, with its executable recipe likewise saved as `--configuration`. For evaluated algorithm source, identity includes source and supplied configuration, so changing the source while retaining settings is a real implementation change. The tool uses declared artifact scope, without guessing from a filename. Changing output scope labels alone does not create a new recipe.

Cards expose `implementation` and earlier same-comparison `reused_implementation_from` IDs. Routes report measurements and distinct artifact fingerprints separately from distinct implementations. Output-only records retain their scores but have a null implementation count and a diagnostic route review; reconcile the actual executed recipe before proposing a code change. These identities assume a complete snapshot: capture intended candidate arguments, feature/data choices and dependency identities in the recipe, while storing declared measurement seeds and run logs separately. Hash equality does not prove that provenance is complete. Earlier costs remain binding, as do user limits that still apply.

New disk events store fixed-size `reuse_links` summaries (first ID, previous ID and count) for artifact and implementation reuse. Existing events remain byte-for-byte intact. `record` still returns complete reuse lists; `brief` reconstructs the displayed lists from actual history, while `read_records` leaves compact events unexpanded. Use the upgraded `brief` with compact events. This removes quadratic repeated-ID storage; a record call still scans history and its complete CLI output can grow with that history.

Archive loading reuses candidate and prior result-digest indexes within one ordered read, rather than rebuilding them for every proposal and successor. Only accepted preceding events enter those indexes; each new read starts from current disk bytes. The JSONL format, validation order, error behavior and evidence checks remain unchanged. This removes repeated prefix work from ordinary proposal replay, not all historical scans in `record`, `brief` or handoff assembly. No persistent cache or new database is required.

A single `brief`, `trace` or campaign handoff also shares a local file-digest reader across its evidence consumers. Each new operation starts empty and reads its referenced files again. Within that operation, a digest is reused only after the resolved path's device, inode, mode, size, modification time and change time still match. Files modified within one second before the operation began are always reread, because adjacent same-size writes can share a filesystem timestamp tick; the tool does not wait. Directories are re-enumerated on every hash, and consumers needing result contents still read those bytes. Only digests are retained. This reduces repeated hashing of stable shared recipes, without changing archive identities or ranking; it is not an atomic snapshot of concurrent edits.

The active route is always shown; alternatives are ordered by their measured representatives in the declared direction. Separately, `review_frontier` retrieves open opportunities from the complete matched development history, including older candidates on the same route and routes outside the score list. An opportunity requires a valid scored execution, a code/recipe snapshot, a promising/unresolved status and explicit feedback. Its representative is the first valid scored execution of that implementation; `feedback_candidate_id` can point to a later measurement that first declared the opportunity. Renaming a route or repeating an implementation does not create another opportunity or replace its representative with a lucky score.

Frontier entries show distinct executed successor implementations, measured successor counts and the latest successor's verified card. Only a measured changed child after the implementation's first opportunity declaration, with a prediction status other than `unresolved`, advances the old opportunity. Failed, partial, unscored and explicitly unresolved children preserve it; an older child cannot close a newly declared opportunity. Repeated declarations cannot revive an opportunity already advanced by a real successor. Legacy measured children without a prediction status retain their previous closing behavior. These links track implementation progress, not proof that feedback was correct or the whole method was exhausted.

Frontier retrieval orders never-exposed implementations first, then least recently exposed ones; archive declaration order breaks ties. The unattended driver supplies successful-checkpoint exposure turns, separately for each comparison contract. Direct `brief` calls are read-only and do not advance exposure, so repeated standalone calls keep archive order. This retrieval order does not select the next parent: inspect objective headroom, unresolved mechanisms, prior children, maturity and cost.

Defaults display four routes, four recent distinct active-route candidates, four matching pending details and two frontier opportunities. `--routes`, `--recent` and `--frontier` change retrieval size only; `--frontier 0` disables the extra selection. They are not candidate budgets or method settings. Older best representatives are retained even outside the recent window. Each displayed route includes its latest failure/rejection; use the archive's referenced records for an older relevant mechanism. Omission counts make the retrieval scope explicit.

Pending work belongs to its **first parent's complete comparison**. List that parent first when proposing a repair or transfer; other development parents and feedback may come from different contracts. The brief keeps their verified implementation, source/recipe paths and result identities in `pending_references`, with `requires_revalidation: true`; their objectives and original feedback stay out of the active score evidence. A repaired successor may acquire a complete scoring contract that the failed parent lacked. Confirmation references remain forbidden.

Standalone `brief` retains all pending IDs and the latest matching details; `matched_pending_proposals` and `pending_summary` identify the active subset and omissions. The unattended packet includes only IDs assigned to the active comparison, then rotates details by successful exposure. It starts with never-exposed work, then the least recently exposed, breaking ties by archive order. Exposure does not fulfill or stop a proposal. Inspect existing artifacts before executing still-useful work or record an explicit stop reason; unchanged code and old results cannot fulfill it.

The unattended packet also derives `trial_history` from completed proposal/result links. It carries the original `basis`, `change`, `expected_observation`, validation and stop condition beside the actual outcome and verified source/result pointers. It selects the latest completed trial whose parent or outcome matches the current/best implementation, then rotates the remaining historical slot by successful exposure; without a related trial both slots rotate. First-parent comparison defines membership. Pending and stopped proposals, output-only records and manual score claims do not become tested mechanisms. Old trials without prospective links remain available in the archive without invented predictions.

For each trial, `objective_gain_vs_parents` is signed in the declared direction only when the outcome and that parent are ordinary development candidates with valid scored executions under the exact active comparison. Diagnostic outcomes and diagnostic parents supply no candidate gain. A foreign-contract outcome or reference supplies identities and paths with a revalidation marker; its structured objective and outcome feedback/prediction status are excluded. `state: measured` describes an observation under the outcome's own contract; check `outcome_comparison_matches` before interpreting it for the active task. Self-reported predictions and explanations are scoped interpretations. A failed or unscored execution leaves algorithm quality unresolved, and changed prerequisites can justify revisiting a mechanism.

Trial exposure commits only after an accepted successful invocation, keyed by comparison and proposal ID. Required IDs, code targets, source/result pointers and hashes must match their pre-bounding retrieval digest. Shortened prose can still point to the full original record; missing necessary identity does not consume exposure. The two slots limit retrieval size only. This view neither chooses a parent nor blocks similar proposals, grants trials or closes the campaign.

Use `trace --archive <path> --proposal-id <ID>` to recover one original proposal outside either retrieval window, including its full `code_targets`, validation, stop condition, input hash when recorded, and current outcome. This checks only the selected proposal's evidence, returns an explicit error for an unknown ID, and leaves the archive unchanged. `trace` is an audit view and may show its development references' original contracts and scores; do not treat cross-contract scores as active ranking evidence. A missing original input hash remains null rather than being reconstructed. Reconcile unarchived processes/outputs separately; exact retrieval does not prove that a partial implementation ran.

The command checks displayed result and snapshot bytes and shown pending code targets. Case-profile retrieval also verifies the historical result bytes used for case comparisons; other unselected history is not fully verified. It does not alter the archive. Missing identity fields are labeled `not_recorded`; legacy evidence does not gain verification merely by appearing in a brief. Adapter validity keeps its checked scope, and score recomputation, training provenance, unchecked hard rules and causal interpretation still require their existing evidence. Reference raw results when detailed errors or components are needed; there is no need to write another summary document.

## Retrieve Complementary Case Evidence

An adapter can opt in with the optional [`case_profile` result field](adapter-contract.md#optional-case-profile). `brief.complementary_evidence` searches all matched ordinary development history, independently of route, recent and open-opportunity lists. It requires at least two aligned cases, a valid completed scalar adapter observation and an actual code/recipe snapshot. Diagnostic, confirmation, failed, manually scored and output-only records cannot supply these parents.

The reference is the best implementation's first valid profile observation under the active comparison; `best_candidate_id` and `reference_candidate_id` can differ if earlier measurements lacked profiles. Each other implementation also contributes its first valid profile observation, never its luckiest repeat. The complete comparison, profile metric, direction and exact case-ID set must match. No cross-contract scores or confirmation losses enter this selection.

At most two retrieved candidates add actual winning cases against the reference. Selection prioritizes uncovered wins, then total wins, the observed scalar score and archive order. A fully dominated candidate has no wins; a second candidate must add a different win. This is a retrieval window, not a candidate allowance or proof that these are the best possible combinations. The evidence shows wins/losses/ties and up to three winning and losing case values, with verified source/result cards. Read the complete profile from its cited immutable result when needed. The archive stores only its metric, direction, count and hashes, not a second copy of the vector. Retrieval keeps one history vector at a time.

Inspect those implementations and cases to derive a legal change: a richer construction, a condition available at runtime, or a combination with evidence of useful error interaction. Record multiple `parent_ids` and relevant `feedback_from` using the existing proposal format, execute the successor and judge the actual objective, validity and cost. Per-case best outcomes do not establish an executable candidate or a score gain. Prediction selection cannot inspect hidden labels at inference; case wins alone are neither necessary nor sufficient for a useful blend. Keep the existing [prediction diagnostics](data-model.md#check-whether-a-two-parent-blend-has-a-useful-direction).

Profiles do not change scalar ranking, objective progress, route/frontier decisions, promotion or completion. Old archive events and sealed requests remain intact; missing profile metadata is not retroactively inferred into an old event. A newly recorded observation can reuse existing verified source/results where appropriate, without rerunning solely to populate retrieval metadata.

The unattended campaign separately surfaces `repeat_conflict` when actual same-contract repetitions reverse first-observation ordering. It requests a task-specific measurement review with verified leader, challenger and witness pointers. It changes neither the scalar representative nor the resource frontier or promotion rule. A fixed protocol must define any paired runs and aggregation before later outcomes are inspected; three recorded scores alone do not authorize taking their mean.

For a conflict, write the plan before running more experiments. Its JSON contains the exact `comparison` from the leader's archived record, `conflict_signature` and three candidate IDs from `repeat_conflict`, a unique `plan_id`, a nonempty task-specific `decision_rule`, and a nonempty `runs` list. Each run has a unique `run_id`, a fixed `seeds` list (empty only if the task has no seed) and a positive `repetitions` count; each run expects one real result for each of the two archived implementations. Archive it with `candidate_archive.py measure-plan --archive ARCHIVE --plan PLAN.json`. The CLI verifies the ordering conflict and source/result snapshots, then appends an immutable `measurement_plan` event. A second plan for the same conflict is rejected.

Each subsequent adapter result carries `evaluation.measurement_plan_id`, `measurement_run_id`, `seeds` and `repetitions`, and is archived through the ordinary `record` command with a reuse reason for unchanged source/recipe. `record` rejects a planless, cross-contract, changed-recipe, wrong-run or wrong-seed result; an invalid/failed result remains an attempt and leaves its slot open. Retrieve the full protocol, matched outcomes and all attempt candidate IDs with `candidate_archive.py measure-status --archive ARCHIVE --plan-id ID`. The campaign packet carries the oldest open plan's ID and next run; it can continue that plan after an interruption or later comparison switch. Only all successful, valid, scored pairs allow a decision. Apply the declared rule to those raw results and archive a JSON conclusion with `plan_id`, `conclusion`, `reason` and `next_action` via `candidate_archive.py measure-decide --archive ARCHIVE --decision DECISION.json`. The decision event binds the exact paired result IDs, values and result hashes; when a later handoff carries it, the paired source/result bytes are rechecked. The archive neither averages old repeats nor changes its first-observation ranking automatically.

If the frozen protocol cannot be completed, use `candidate_archive.py measure-stop --archive ARCHIVE --plan-id ID --reason TEXT --next-action TEXT`. Describe the failure or unavailable prerequisite and a concrete repair or alternative. This appends `measurement_stop`, automatically binding the frozen protocol and every archived attempt, including failed and invalid runs. Writing the stop and carrying it in a later handoff recheck the cited source/result bytes. `measure-status` reports `state: stopped_unresolved`, preserves successful slots, failed attempts and the actual `complete` flag, and records no paired conclusion. A stopped plan is no longer scheduled and rejects later tagged results, decisions and repeated stops; the same conflict cannot acquire a replacement plan. Fixing its source/recipe creates ordinary development evidence rather than filling the old slot. Execution health still requires a usable scored observation after a failure. The handoff's `measurement_stop` carries the reason, next action, remaining slots, attempt counts and comparison scope across restart. Only a newly archived stop matching the active comparison may replace the receipt's next action; historical stops cannot repeatedly overwrite later plans. Stopping a measurement plan does not stop the campaign or change candidate ranking.

## Retrieve Measured Resource Tradeoffs

If the fixed adapter provides an explicit resource_profile, brief.resource_tradeoffs retrieves observed quality/resource endpoints and the normal candidates mapping includes their checked source/recipe and result pointers. The driver injects this view into the next invocation. Inspect the measurement protocol and both implementations to choose a useful parent, complete an alternative mechanism or construct a multi-parent successor. Evaluate that actual successor; quality and speed gains do not automatically combine. A field shortened by packet bounding is a retrieval hint: recover its original source/result before acting.

Selection uses only successful, valid, scored ordinary development implementations with real code/recipe snapshots in the complete active comparison. The best scalar implementation's first valid profiled observation selects the resource protocol; if unavailable, use the anchor implementation's first profile. If neither has one, the view remains empty and reports the number of observed protocol groups instead of silently choosing another. The reference candidate can differ from best_development; each selected point uses quality and resource from that single profiled result, never a scalar score from another run.

Within that exact metric/unit/scope/protocol group, the first valid profiled observation per implementation represents it. Repeats cannot win by their luckiest score or fastest time. This is an observation policy, not repeated-measurement aggregation, denoising or an uncertainty estimate; a lucky first observation can still be misleading. Use the task's measurement and confirmation protocol when consequential.

Resource is minimized and quality follows its declared direction. A point is dominated only when another has no worse quality and no greater resource, with at least one strict improvement. Equal points use archive order. A sorted scan computes the observed subset frontier; at most two distinct endpoints, fastest then highest quality, are displayed, with omitted interior-point count. These retrieval hints do not limit experiments, prove global Pareto optimality, impose weights/resource limits, promote a candidate or change scalar progress. Confirmation, diagnostics, partial/failed runs, manual scores and output-only artifacts cannot populate the view. Raw results retain all measurements; no old archive migration is needed.

## Diagnostics and Contenders

Record intentional ablations or counterfactuals with `record --role diagnostic --parent CONTROL ...`; the first parent must be an ordinary development control. Additional parents and proposal feedback may reference development or diagnostic records. Confirmation/test/holdout evidence cannot supply diagnostics. Default `development` remains the role for a genuine improvement attempt, including a regression; a low score alone does not make it diagnostic. Diagnostics cannot be `incumbent` or `runner_up`. A completed diagnostic can keep `status=unresolved`: status describes investment, while its result and `trace` show whether execution completed.

Preserve the intervention's actual source/configuration, result and cost. A prospective proposal should state the question, controlled change and expected observation before execution. Feedback remains a scoped interpretation: a score change can motivate a code change without proving a general causal rule. A failed or unscored diagnostic still needs execution repair.

Analysis of existing outputs, such as [cached inference vote replay](inference-vote-replay.md), produces supporting evidence rather than a new executed candidate. Put the report path/hash in a proposal's `basis` or `validation`, or the decision card; `feedback_from` continues to contain existing candidate IDs. Do not pass the replay report as an adapter result or invent a candidate/score for it. After implementing the selected policy, archive the task adapter's actual outcome through the ordinary proposal/successor path.

`brief.diagnostic_evidence` retrieves the latest two diagnostics whose first control matches the active complete comparison, with available/omitted counts and the control card. This is a retrieval window, not an experiment allowance. Same-contract cards expose `role` and measured objective, with no gain against the best; foreign-contract diagnostics expose verified identity/pointers in `pending_references`, without their objective or original feedback. Proposal ownership still follows the first parent's own comparison. For a transfer into the current contract, list its ordinary control first and use the foreign diagnostic as a secondary parent or feedback reference.

Diagnostics do not enter best/route ranking, candidate stagnation, comparison singleton signals, or close an ordinary `review_frontier` opportunity. Their prospective outcomes remain recallable in `trial_history`, carrying `outcome_role` and evidence roles. Use the observation to choose and implement a real successor. If a diagnostic implementation becomes a contender, establish the task's complete validity/comparison evidence and explicitly record it as development; retain a reuse reason when reusing a tested snapshot/result instead of rerunning an unnecessary experiment.

## Record One Actionable Proposal

Read the relevant parent code and matched feedback. Choose the next implementation using the [task/code/history proposal guidance](score-search.md#propose-from-task-structure-code-and-history), with applicable resource constraints and the nearest credible alternative in mind. Save one compact JSON proposal and link it from the decision card; do not also write a separate report or duplicate the proposal fields in other notes. For example, an algorithm candidate might use:

```json
{
  "proposal_id": "complete-neighborhood",
  "parent_ids": ["cand-03"],
  "feedback_from": ["cand-03", "cand-05"],
  "route": "block-neighborhood",
  "code_targets": ["D:/competition/run/cand-03/solution.cpp"],
  "basis": "Matched results show the pair-swap search stalls with a remaining block-assignment gap; the prior cache change did not alter that limitation.",
  "change": "Implement the complete block reassignment neighborhood and its constraint-preserving decoder.",
  "expected_observation": "Valid block changes escape the stalled state and improve the full development objective within the legal runtime.",
  "validation": "Use the unchanged evaluator/workloads; check constraints, score components and total runtime against parent and incumbent.",
  "stop_condition": "Stop on user request, an applicable hard/resource constraint, an observed unresolved blocker or verified task completion. An exhausted route triggers strategy review."
}
```

Replace the example path and hypothesis with this task's verified snapshot and evidence. In ordinary refinement, `parent_ids` are the implementations being changed or combined; `feedback_from` are the relevant development results, which may differ from the parent. `basis` explains why the change follows from task facts, sources or observations. For a new task-derived route, put its derivation and component dependencies in `basis` without inventing a measured bottleneck; the independent mode below separates comparison controls from source inheritance. No prior successful trial is required. The script checks identities and links, not whether the diagnosis is scientifically correct.

For a user-inspired proposal, include the short original idea or its message/note reference and the interpreted mechanism in `basis`; this text is retained in both `brief` pending details and `trace`. Keep `feedback_from` bound to actual development candidate IDs, including a baseline when needed, rather than inventing a result ID for a user message. Extra arbitrary proposal fields are not retained by the helper. After execution, connect the measured outcome back to the tested idea in `--feedback`. Follow [user-idea handling](score-search.md#turn-user-ideas-into-experiments) when deciding priority or handling new input.

For modeling, the parent record should include predictions as `--source` and a compact immutable training-code/recipe directory as `--configuration`; `code_targets` names a file inside that directory. Evaluated predictions are outputs, not code targets. For an algorithm, the target can name the archived source or an applicable configuration file. The proposal command verifies parent artifact/result bytes and binds the targets to the executable snapshots. Unrelated files, changed parent bytes, missing produced-output recipes, unknown IDs and confirmation feedback are rejected.

```powershell
python <skill-dir>/scripts/candidate_archive.py propose `
  --archive <run>/candidate-archive.jsonl --proposal <run>/proposal-07.json
```

The proposal is now `pending`. Create an isolated candidate directory, implement the change, check duplicates, and execute the adapter now. Copy the needed parent components or build a standalone replacement behind the same interface; preserve the parent snapshot. The tool does not run embedded commands, generate a method or impose/renew a budget. A missing code snapshot should be reconciled from the actual executed artifacts, rather than manufactured for the record.

## Declare an Independent Construction

When a new representation or algorithm is constructed without inheriting parent implementation components, add `"construction_mode": "independent"` to the prospective proposal and set `"code_targets": []`. Keep nonempty `parent_ids` naming verified development comparison controls and `feedback_from` naming relevant development evidence. The first control still defines comparison ownership; a new route does not create permission to compare incompatible evaluations. Describe the task-derived structure and coupled components in the existing `basis` and `change` fields. Do not fill an unrelated old file as a fictitious modification target.

The mode defaults to `refinement` when absent, preserving old records. Refinement requires actual parent file targets; explicit independent mode requires an empty target list. Parent snapshots and results still undergo existing identity checks. Construct the source or complete executable recipe in an isolated directory from the task/interface, retaining required interface context rather than automatically copying unrelated parent code. If the design actually reuses or combines parent components, use refinement.

Record the executed successor with the same `--parent` IDs and `--proposal-id`; the helper copies the explicit mode from its prospective proposal. New executable source/recipe and a new adapter result are still required. Output-only records, confirmation evidence, unchanged recipes and recycled execution results cannot bypass the existing guards. Matched gains remain observed comparisons against the listed controls, not evidence of code inheritance or causation.

`brief` pending details, exact `trace`, candidate cards and `trial_history` preserve the explicit mode. Identity checks show `code_targets=not_applicable, construction_mode=independent` instead of claiming nonexistent file checks. Pending/trial handoff accepts the legal empty target only with the independent mode and matching identity markers; missing, altered or truncated mode cannot count as an intact handoff. An independent successor may itself open a new opportunity, but it does not count as a refinement successor or close an opportunity on its comparison control. Legacy events are unchanged.

This is an Agent declaration of source reuse intent, not proof of algorithmic novelty, freedom from anchoring or an information-isolation boundary. The driver still exposes development history. No default fresh-start schedule, extra provider, candidate quota or promotion rule is introduced.

## Attach the Measured Outcome

After evaluation, explain the actual observation and whether the prediction was supported, contradicted or unresolved. Attach the proposal when recording the candidate:

```powershell
python <skill-dir>/scripts/candidate_archive.py record `
  --archive <run>/candidate-archive.jsonl --candidate-id cand-07 `
  --parent cand-03 --proposal-id complete-neighborhood `
  --source <run>/cand-07/solution.cpp --result <run>/cand-07/result.json `
  --route block-neighborhood --mechanism "complete block reassignment" `
  --status promising --prediction-status supported `
  --feedback "Valid block moves escaped the stalled state; runtime cost and the full score determine further investment."
```

Use the measured outcome, not the example's `promising`/`supported` labels. Failed implementations use `rejected` or `unresolved`, keep the failure, and do not establish method quality. The successor must match the proposal's parents and route, change the evaluated artifacts, supply a new completed adapter result and include feedback/prediction status. Produced outputs require a changed executable recipe: fresh predictions from any unchanged parent cannot fulfill a code-change or combination proposal. Algorithm source may change while its ordinary configuration stays fixed. Necessary unchanged measurement remains an ordinary record; an exact artifact repeat uses `--reuse-reason`. The archive automatically links different output bytes from the same complete recipe as repeated implementation measurements.

Different fingerprints alone do not prove a substantive algorithm change. The agent still reviews the code difference, hard rules, maturity, cost and full-objective comparison; do not edit comments or rename artifacts to satisfy the check. Adapter validity keeps its declared scope. Unknown total score and partial-rule coverage remain limitations even when an implementation ran.

## Review the Actual Implementation

If a successor may have omitted or substituted the proposed mechanism, inspect its executed source against the original proposal. Record fidelity independently of `prediction_status`: the latter describes whether the expected observation occurred, while fidelity describes which mechanism reached the code. An unexpected low score does not establish that an absent component failed; a strong alternative remains a measured candidate even if it differs from the proposal. Decide whether a missing component still merits implementation rather than automatically retrying it.

Pass `--implementation-review <run>/review.json` on the same `record` command that attaches the measured successor. The optional JSON input is:

```json
{
  "fidelity": "partial",
  "actual_mechanism": "The successor evaluates one replacement but does not refill the freed capacity.",
  "missing_components": ["Refill each tentative replacement before comparing its full objective"],
  "code_evidence": [
    {"path": "/absolute/run/cand-07/solution.py",
     "detail": "The exchange loop compares only the inserted item's profit; no refill follows it."}
  ]
}
```

Use the actual file and observation, not this example. `fidelity` accepts `yes`, `partial`, `no`, or `unknown`; `yes` requires no missing components, `partial`/`no` require at least one, and `unknown` permits either. At least one concrete code citation is required. The helper resolves and hashes each file, binds it to the successor implementation fingerprint and proposal ID, and stores the normalized report plus the raw JSON SHA-256 in the append-only candidate record. The raw review file is not required afterward. File hashing verifies identity, not whether the report correctly describes program semantics.

Reviews require a proposal-linked, actually executed development or diagnostic snapshot, including failed executions. Manual scores, confirmation records and output-only artifacts cannot carry one. For prediction/generated-output tasks, citations must name the executed recipe/configuration snapshot, not the prediction file. For directly evaluated programs they must belong to the successor source/configuration artifacts. A parent file or unrelated workspace file is not evidence of the successor.

`brief`, exact `trace`, and matched `trial_history` evidence retain `implementation_review` as an `agent_report`, with hashed code paths. Trial cards from other comparison contracts omit this prose and require revalidation. The bounded driver packet seals an included review with its required identities; shortened or changed reports do not count as delivered trials. Retrieve the full trace when necessary. Old records remain unchanged and absence means unknown, never implicit `yes`. The report does not change scores, validity, ranking, objective progress, promotion or stopping rules, and it proves neither causation nor semantic correctness.

## Carry Conditional Learning into the Next Construction

Raw `trial_history` rotates at most two completed attempts into each handoff. A useful conclusion can outlive that window. Optionally pass `--learning <run>/learning.json` on the `record` command for an actual proposal-linked, scored development or diagnostic successor:

```json
{
  "key": "exchange-and-refill",
  "lesson": "The measured exchange only helped when its freed capacity could be refilled.",
  "conditions": "The matched workload includes feasible smaller items in the remaining capacity.",
  "next_action": "Compare complete exchange-plus-refill alternatives before accepting a move.",
  "limitations": "This is an interpretation of the cited development cases, not a universal rule.",
  "evidence_from": ["cand-06"]
}
```

Use actual observations and IDs. The current successor is added to `evidence_from` automatically. Every cited outcome must have an executed, valid, scored source/recipe snapshot under the same **complete comparison**. Manual scores, failed/unscored runs, output-only records without a recipe and confirmation records cannot supply learning evidence. They remain available through their existing diagnostics and recovery paths. A new report binds the original proposal, comparison, raw input SHA-256 and verified source/result identities, marked `assessment_kind=agent_report`. The raw input file is no longer required for retrieval.

Use the same descriptive `key` for a conclusion being revised. Supply `revises` with the current report's candidate ID and include that ID in `evidence_from`; the new measured successor supplies the new observation. A stale revision or silent replacement is rejected. Earlier reports and original archive bytes remain intact. Different comparison contracts maintain separate conclusions even when keys match.

`brief.scoped_learning` returns current revisions with the actual conditions, limitations, next action and verified source/result pointers. It prefers implementations related to the anchor/best and then recent reports, displaying at most two with omission counts. This is a retrieval window, not a search budget. To read an omitted report, find its candidate's `proposal_id` in the archive and request `trace --proposal-id <id>`; the outcome evidence contains its complete `learning`.

Campaign handoffs use the same two-report window differently: at most one recent related current head stays visible; the other positions rotate never-delivered heads first, then least recently delivered, with archive order breaking ties. A head is identified by its candidate ID, so a new explicit revision receives a new chance and a superseded report never re-enters the current pool. Exposure is isolated by complete comparison and saved only after a successful checkpoint with the entire report and its evidence identity intact. Preparation, failed CLI calls, invalid receipts and truncated reports do not consume it; resume preserves it. Standalone `brief` keeps its related-then-recent ordering and does not advance campaign exposure. Successful delivery does not prove the agent read or applied a conclusion; record actual use through `learning_from`.

When a report changes a new construction or diagnostic, add `"learning_from": ["cand-07"]` to that prospective proposal and explain the application or counterexample in `basis`. The IDs must be current report heads under the first comparison parent's contract when proposed. They need not also be parents or `feedback_from`: comparison controls, feedback and learning play different roles. Later revisions do not rewrite an already pending proposal. Source/result bytes are checked again on retrieval and application.

The archive carries `learning_from` through pending details, the executed successor, exact trace and matched trial handoff. Trace additionally returns the original cited reports as `learning_evidence`; matched trial cards retain them and the existing delivery seal detects changed or truncated reports. A cross-contract card omits report prose and supplies revalidation pointers. If bounded context omits details, retrieve the exact trace rather than guessing the lesson.

Learning remains the Agent's interpretation. Hashes bind evidence identities, not semantic truth or causal explanations. Inspect the cited code/results, revise conditions when new evidence disagrees, and let actual evaluation decide improvement. This optional path adds no model call, ranking gate, method blacklist, forced trial count or stopping rule.

When a proposed action cannot be run, preserve it as pending or close it with a concrete stop:

```powershell
python <skill-dir>/scripts/candidate_archive.py stop `
  --archive <run>/candidate-archive.jsonl --proposal-id complete-neighborhood `
  --reason "The required input data is unavailable after checking the declared source; preserve this proposal until the blocker is resolved."
```

One proposal has one outcome. A repair or revised mechanism gets its own proposal, citing the previous development result. An interrupted process or partial adapter write stays pending until reconciled; do not mark it evaluated merely because a command was launched.

## Resume and Deliver the Actual Chain

```powershell
python <skill-dir>/scripts/candidate_archive.py trace `
  --archive <run>/candidate-archive.jsonl --recent 8
```

`trace` shows feedback -> proposed code change -> evaluated successor or stop. It verifies the displayed result and artifact identities once per candidate, reports prediction status and costs, and computes signed gain against parents only when valid scalar development results share the comparison identity. Missing/unknown scores and incomparable or invalid outcomes return no gain; they are not promoted. Positive gain is developmental evidence, not independent confirmation or proof of causation.

The default returns the last eight proposals and **all pending IDs**, so older unfinished work remains visible without loading every historical result into context. Use `--all` for a full audit. A proposal without a linked successor stays pending even if other candidates were evaluated. Legacy trials remain in the archive; absence of a prospective link does not mean they were never run.

Legacy records need no rewrite. Known prediction scope and existing recipe hashes supply their implementation identity when available; older linked outcomes retain their original acceptance scope. The evidence view labels an unavailable recipe, and prospective code-change proposals require the actual executed snapshot. A legacy output link alone does not establish that its source code changed.

On resumption, reconcile pending artifacts/processes before retrying. At delivery, include the compact actual chain, then follow the existing freeze/confirmation rules. A successful trace is evidence of linked execution, not grounds to stop while a useful feasible successor remains. Retrieval window sizes never limit the number of optimization iterations.
