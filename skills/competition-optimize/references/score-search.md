# Search for Score Improvements

Read this when selecting or revising solution routes and their experiments. Optimize the contest objective using evidence and unresolved questions. A candidate is an executable method/configuration, not a prescribed small mutation. There is no default time, cost, trial or round cap: budget/reserve checks below apply only to currently applicable user limits, competition rules or actual finite resources. Record costs even when no cap applies.

## Efficient Proposal and Quality Gate

Use one short reconnaissance pass before implementation. Read the task contract and current candidate identity, recover the independent task formulation, map the score-affecting path, inspect profiles or error slices if already available, and retrieve only relevant matched trials. Reuse hashes and summaries instead of rereading unchanged logs. The pass ends when it supports choosing a concrete mechanism or a specific diagnostic would change that choice. A task-derived construction or representation need not first appear as a measured code bottleneck.

Choose the next proposal by four practical questions: does it address a task-derived opportunity or observed limitation, is there a coherent mechanism with applicable prerequisites, is it feasible with available resources, and would its result change promotion or the next proposal? Prefer a complete change with meaningful headroom. Prior measured gain is not an entry requirement for a novel mechanism. Stop expanding the route list or polishing an explanation once these questions are answered and implement within the requested scope.

Before a full evaluation, run a quality gate appropriate to the adapter:

- Candidate source/configuration is snapshotted and hashable; the evaluator, fixtures, split/workload and score model are unchanged.
- The interface, hard rules, known-answer checks and files needed to execute the declared stage pass. Submission packaging belongs to delivery unless execution/interface validation or an explicit user request needs it earlier.
- Any cheap screen has a documented relation to the full objective and is used only to reject invalid or clearly weak candidates; otherwise go directly to the matched full comparison.
- The comparison records parent/current-best IDs, objective direction and components, worst relevant regime, runtime/memory or inference cost, and the exact reproduction command.

Failing the gate is an implementation or measurement problem, not evidence that the proposed mechanism loses. Repair an identifiable cause when a useful correction exists; each retry needs a changed implementation or resolved prerequisite. Otherwise preserve the failure and choose the next proposal. Passing the gate does not promote a candidate without the full declared comparison. This gate reduces wasted runs while keeping quality decisions tied to the actual objective.

## Propose from Task Structure, Code and History

Use the problem's objective and constraints, user ideas, applicable strong solutions, and the current implementation's evidence to derive the next optimization. At initial formulation or after a consequential new source, use [strategy derivation](strategy-design.md) to ask what a good solution would look like without the incumbent's design. Then inspect its representation, execution path, objective updates, pipeline or policy to identify the actual capability difference. Retrieve only pertinent history, preserving its evaluator, scale and resource scope; a remembered summary is reusable only when its referenced artifacts still match. Ordinary refinements can reuse this model.

Produce one short actionable proposal using the existing decision card or notes:

| Basis | Content needed for the next implementation |
| --- | --- |
| Task or source basis | The task fact and derivation, or inspected reference mechanism and its prerequisites; label conjectures |
| Current code | Snapshot/path and relevant component or standalone replacement target; the limiting behavior or missing capability |
| Historical evidence, when available | Pertinent trial/result IDs, what worked or failed, and why this differs from a rejected implementation; missing history does not bar a new route |
| Optimization mechanism | Concrete replacement or change, coupled components, expected effect on the declared objective and resources |
| Test and cost | Observable prediction, validity checks, matched comparison, rejection condition and implementation/evaluation cost |
| Novelty and decision | Fingerprint/parent, archive entries it differs from, route choice (exploit/explore), and what result would trigger the next switch |

Treat the diagnosis as a hypothesis when evidence does not establish its cause. Compare the proposal with the nearest credible feasible alternative when that changes the choice. Implement the chosen proposal now. The proposal is an execution decision, not another report to finish before coding.

Parameter search is not the default: no automatic grids, random/Bayesian searches, neighboring-value sweeps or seed hunting. Run a dedicated tuning campaign only when the user explicitly requests one. Internal settings may change as part of a code-supported mechanism; the tested proposal must explain that mechanism rather than enumerate values. History may favor a local change or a complete method replacement; do not force either solely from an action menu.

## Turn User Ideas into Experiments

Accept natural-language input without a mandatory form. Retain the short original idea or its message/note reference in the existing proposal's `basis`, followed by the agent's interpretation, assumptions and code/history context. Use `change`, `expected_observation` and `validation` for the actual implementation and test. No separate idea database or additional archive field is needed.

| User input | Effect on the next action |
| --- | --- |
| A rough hypothesis, domain observation or “for consideration” | Check its task fit and compare a concrete test with the best alternative; implement or give a specific deferral reason |
| “Try this first” or “implement and compare this” | Prioritize that legal feasible test; a speculative low gain is not grounds to silently substitute the agent's preferred route |
| An explicit requirement or prohibition | Apply it at its stated scope; check its compatibility with competition rules and update affected implementation decisions |
| “Discuss only” or “do not change code yet” | Analyze the idea within that scope; do not count discussion as an executed candidate |
| “Learn this high-scoring solution's thinking” | Explain its central design, derivation, component dependencies and difference from our method using [strategy learning](strategy-design.md#read-a-strong-solution-as-a-system); benchmark only when needed for the requested conclusion |

Translate the intended mechanism into a complete minimal implementation, not merely a nearby parameter change. For example, “perhaps pair swaps get stuck” can motivate a larger valid neighborhood after inspecting the move generator and stalled trace; “these errors may depend on time” can motivate a permitted time signal or a split-mismatch diagnostic. These are interpretations to test, not facts supplied by the user. Check the smallest consequential uncertainty first; absence of a previous measured gain does not disqualify a novel hypothesis.

When wording admits materially different implementations, ask one targeted clarification and continue independent useful work. If the choice is routine, state the assumption and proceed. Establish a credible baseline if none exists. If a comparable experiment already tested the same interpretation, show its evidence and the changed prerequisite needed for another informative test; honor an explicit request for a matched repetition while recording it as a measurement. An infeasible or rule-conflicting idea needs the concrete obstacle and a compatible alternative preserving its purpose where possible.

Input received during a trial steers the ongoing task. At the next safe decision boundary, reconcile the process/artifacts, update the next action and use the new idea without discarding measured history or restarting unchanged setup. An explicit stop/cancel or incompatible new requirement takes effect immediately. Preserve superseded unexecuted proposals with their reason instead of marking them evaluated. If an idea arrives after the shortlist is frozen, test it on development evidence; confirmation-informed changes need fresh confirmation.

After the test, report the user's idea, the interpretation actually implemented, its candidate/result, the matched score/resource comparison and the next action. Keep “supported,” “contradicted” and “unresolved” scoped to that implementation and evidence. Deferral means untested, not rejected. Carry only decision-relevant pending ideas in the current card so later continuation can act on them.

## Candidate Archive and Route Switching

Keep `candidate-archive.jsonl` or an equivalent record in the run directory. Each entry should include candidate ID, parent IDs, source/configuration fingerprint, route/mechanism, evaluator and workload hashes, validity, objective components, resource cost, status (`incumbent`, `runner_up`, `promising`, `rejected`, or `unresolved`), and the evidence that permits or blocks further investment. Store a short failure mechanism for invalid or weak candidates instead of only a score.

For a mechanically checked JSONL archive, use [`candidate_archive.py`](../scripts/candidate_archive.py). For example:

```powershell
# Retrieve matched best code, failures and unfinished proposals for this decision.
python <skill-dir>/scripts/candidate_archive.py brief `
  --archive <run>/candidate-archive.jsonl

python <skill-dir>/scripts/candidate_archive.py check `
  --archive <run>/candidate-archive.jsonl --source <run>/cand-07/predictions.csv

# Evaluate using the task adapter, then record its immutable result.
python <skill-dir>/scripts/candidate_archive.py record `
  --archive <run>/candidate-archive.jsonl --candidate-id cand-07 `
  --parent cand-03 --source <run>/cand-07/predictions.csv `
  --result <run>/cand-07/result.json --route histogram-tree `
  --mechanism "complete tree pipeline replacing the linear model" --status promising `
  --feedback "Observed nonlinear errors improved; missing interaction features warrant a successor"

# Optional advisory review when deciding whether the route has stalled.
python <skill-dir>/scripts/candidate_archive.py decide `
  --archive <run>/candidate-archive.jsonl --output <run>/route-decision-02.json --append
```

Record the baseline first, since parent IDs must already exist. `check` hashes files/directories and blocks exact artifact repeats; `record` preserves results, costs and feedback without changing old events. Give necessary unchanged repetitions or confirmation an explicit `--reuse-reason`; they remain measurements of the same implementation, and do not create novelty or reset the budget. Configurations are optional `--configuration <snapshot>` inputs. Semantic near-duplicates still need code/history review.

Use [`brief` retrieval](iteration-trace.md#retrieve-evidence-for-the-next-implementation) instead of loading every recent record plus separate route and pending summaries. It preserves older best versions, retrieves matched failures and gives code/result locations in one view. Compare the latest feedback with the best version before choosing the parent. Retrieval is read-only and does not replace code inspection, proposal generation or execution; no additional ledger or report is required.

For modeling tasks, `--source` is the evaluated prediction artifact, whose bytes must match `candidate_hash`. Put the training code and recipe in a compact immutable directory passed as `--configuration`. Before fitting, `check --configuration <directory>` can reject a repeated pipeline even though new predictions do not yet exist; after fitting, record both predictions and that directory. The preflight checks only supplied artifact hashes. Include both when a different pipeline yields identical predictions; do not snapshot data, evaluator code or large run logs into the pipeline directory.

Record the complete executable recipe, including intended candidate arguments and feature/data identities. The archive distinguishes this implementation from its produced output: different stochastic predictions from unchanged training count as repeated measurements, and do not add route progress or a new representative. All raw scores and costs remain available. For an algorithm, source and configuration jointly identify the implementation; changing source can keep the same settings. Output-only history preserves scores but cannot establish distinct code/recipe changes. See [implementation scope](iteration-trace.md#retrieve-evidence-for-the-next-implementation).

Result fields supply validity, score direction/kind, stage and dependency hashes; explicit flags cannot contradict them or turn a failed/partial result valid. A fingerprint identifies artifacts separately from evaluation identity. `decide` uses only distinct valid development implementations with the same evaluator, workload/split, score model, evaluation configuration, stage and environment. It checks result bytes, compares against the route's historical best, and excludes confirmation evidence, including from alternative-route ordering. Missing scalar score identity or invalid/incomplete evidence produces `diagnose`; no maximize/minimize direction is invented. Fixed-timeslot results lack an official total score, so they remain archived components unless an explicit declared objective and its comparison dependencies are supplied.

`exploit` means recent historical-best progress or a feedback-supported opportunity; `explore` means a route review is warranted after comparable weak results. An unresolved candidate needs a concrete feedback explanation, and a recorded successor supersedes it. Window defaults (`--recent 4 --min-stagnant 2`) and tie tolerance are provisional advisory policies, never promotion gates or fixed exploration quotas. The agent checks applicable resources, diagnoses the code, and implements the next proposal; the tool does not choose a method or tune parameters. Validity retains the adapter's checked scope; hard rules, training provenance, artifact availability and score recomputation still use their existing checks. Run one archive writer at a time. A partial or corrupt JSONL event blocks further appends; reconcile it before continuing.

Before a new implementation, compare its fingerprint and mechanism with the archive. A duplicate or near-duplicate needs a changed prerequisite, a diagnosed defect, or a new resource/evaluation regime; a new filename is not novelty. Preserve a runner-up when its tradeoff or route may matter, even if it does not beat the incumbent.

Choose between two actions after each valid comparison:

- **Exploit** a route when its code/history shows a specific unresolved mechanism, progress at a legal cap, or a complementary strength worth completing.
- **Explore** a different route when the current route has repeated comparable weak results, a saturated mechanism, or no supported follow-up. Change representation, model family, neighborhood, data signal, objective component, or policy logic as the task permits.

Record route switches as candidate implementations and use them to avoid a sequence of cheap edits monopolizing the search. Do not impose a fixed exploration quota; use archive evidence, objective headroom and actual resource costs. Keep a confirmation reserve only under a finite constraint. Report the reason for every switch or continued investment.

## Compare Routes Before Choosing Variants

The outer decision is **which mechanism deserves effort**; the inner decision is **which concrete implementation tests it**. Derive alternatives from the task independently of the incumbent, then use code and history to judge their actual differences, prerequisites and cost. Do not wait for repeated failed patches before considering a different formulation or learning a newly supplied strong solution. If constraints, prior matched evidence or resources favor a supported local change, explain that choice. Do not force breadth when the baseline is already near a credible bound.

Compare a few routes from task structure, baseline behavior and relevant sources. Keep only the information needed to choose an executable test in `research.md` or existing notes; the table below is optional. Drafting ideas does not consume candidate slots, but research and implementation consume time. Do not postpone a complete prototype to fill a route inventory. Establish viable representatives, then invest in supported mechanisms rather than giving every route an equal quota.

| Route field | Decision it enables |
| --- | --- |
| Route ID and mechanism | Distinguish representation, algorithm/model family, data/training signal, policy, and parameter variants |
| Evidence and prerequisites | Explain why the route fits this objective, scale, data, rules, and resources; retain the source/version |
| Objective headroom | Identify a fixable failure, stronger reference, bound, or missing capability; label unsupported gain estimates |
| Minimal complete prototype | State the smallest executable implementation that actually tests the different method, not an incomplete stub |
| Cost and continuation | Include implementation, evaluation, likely full-fidelity follow-up and combined inference cost; say what justifies deeper work |
| Status and best representative | Candidate/result IDs, tested maturity/resource limit, and supported, unresolved, or rejected mechanisms; keep investment eligibility separate from incumbent rank |

Compare the next proposed variant with the strongest affordable alternative route. Prefer the action with credible potential to change the best solution or resolve a consequential uncertainty; do not assign numerical expected gains without a basis. A tiny test can reveal a large opportunity, and a large rewrite can still be low value. Record the chosen route and why its nearest alternative was deferred; a short sentence at a decision boundary is enough.

Typical structural changes are algorithm/representation/encoding/neighborhood replacements; model/feature/pipeline changes; different permitted data or training objectives; and changes to observations or planning in a policy. Thresholds, weights, seeds, and neighboring hyperparameters are usually refinements of an existing route. The classification explains the search, not a mandatory schema or a ban on a useful cheap tweak.

A cache, a target-window filter or an extra cleanup pass inside the same optimizer usually tests a component refinement. Name it accurately. When repeated local refinements fail, implement a complete alternative method that addresses the limiting mechanism rather than renaming another local patch. Output equality with the incumbent is a useful check for an intentionally equivalent speedup; it must not exclude valid different solutions in a score-seeking route comparison.

Use one interpretable hypothesis or **coherent pipeline transition** per candidate. A new model may need different preprocessing, and a new representation may need a decoder and search moves; implement the coupled change together. Compare the complete candidate first. Use selective ablations only when attribution would change the next investment or final combination; without them, claim the whole pipeline's observed gain rather than identifying one component as the cause.

Repeated refinements with negligible objective gains, improvements within noise, or the same unresolved failure warrant [plateau recovery](plateau-recovery.md): distinguish score headroom from unavoidable loss, use feasible stronger solutions when informative, and test the missing capability in a complete prototype. Check [maturity evidence](#decide-whether-to-repair-deepen-or-retire) before attributing flatness to the method. Keep successful incumbents and rejected evidence; apply only actual constraints, without inventing a gain threshold or round cap.

## Turn Research into Testable Mechanisms

Search from the task family, objective, ideal solution structure, scale and constraints, adding the incumbent's representation or a concrete bottleneck when relevant. Searching only the current implementation's vocabulary can hide other formulations. Prefer relevant original writeups, task documentation and corresponding source versions. Use [strategy learning](strategy-design.md#read-a-strong-solution-as-a-system) to reconstruct the design before extracting a module or constant; check the evaluator when a reported objective or validity claim matters. For implementation requests, move to a complete prototype once the mechanism and prerequisites are understood. For learning requests, deliver the reasoning and its implications before proposing tests.

Convert useful sources into the hypothesis queue below. Record URL/version, license where reuse matters, prerequisites, and a cheap transfer test. Separate author-reported outcomes, inspected implementation, and local measurements. Historical wins, stars, or votes do not establish transfer. Read only the relevant section of [the task-family guide](task-playbooks.md) for concrete experiment options.

## Diagnose Before Choosing a Trial

Break the baseline down by score component and representative case group. For each weak group, distinguish a poor solution from a measurement or implementation defect. Estimate the available improvement from bounds, small exact solutions, a stronger reference, or a targeted ablation when practical. A low raw metric is not necessarily fixable or heavily weighted in the contest score.

For supported CSV predictions, [paired development error analysis](data-model.md#diagnose-development-errors) can expose concentrated loss and slice regressions using saved predictions. Use its observations to propose a falsifiable mechanism, then evaluate any change on the full declared objective. A slice metric, majority of case wins, or loss concentration is diagnostic evidence; none changes the official aggregation or establishes that the errors can be fixed. Use the corresponding workload/episode diagnostics for algorithm and simulation tasks when available.

For LLM entries, inspect generated-answer coverage, selection errors, output validity and exhausted budgets using [the LLM/agent guide](llm-agent-competitions.md#choose-the-layer-from-evidence). [Fixed-answer vote replay](inference-vote-replay.md) compares the declared cached sample budget with irreversible-lead stopping. It does not measure a new candidate, generate a missing correct answer or estimate new engine/batching performance. Use its report to justify a concrete policy implementation and matched real evaluation; keep diagnostic exact-match statistics separate from the official objective.

Keep only decision-relevant hypotheses in the existing proposal/notes or `research.md`; do not duplicate a proposal to populate another queue. Useful fields are:

| Field | What it must make clear |
| --- | --- |
| Mechanism and target | What changes and which score component or case regime should benefit |
| Route and change scope | Which solution family it tests, and whether it replaces a method/pipeline, refines a supported mechanism, or combines parents |
| Parent and evidence | Candidate IDs, source or local result, and the remaining uncertainty |
| Prerequisites | Data, rules, scale, solver behavior, or resources needed for the idea to apply |
| Prediction and rejection test | An observable outcome and the cheapest useful experiment that could contradict it |
| Cost and next decision | Implementation/evaluation cost, failure condition, and whether success justifies a larger trial |

Prefer plausible objective gain per unit of total experiment cost while keeping room for unfamiliar mechanisms. Numeric gain predictions are estimates, not results.

## Decide Whether to Repair, Deepen, or Retire

After a weak result, decide two things separately: whether this candidate beats the incumbent, and whether its route merits another experiment. A valid low score can answer the first without answering the second. Record the narrowest supported conclusion; "not promoted" is not a diagnosis or proof that the entire route is unsuitable.

| Evidence from the trial | Supported conclusion and next choice |
| --- | --- |
| Broken interface, invalid output, or a failed known-answer check | The implementation failed to test the mechanism. Consider a bounded repair if its cause is identifiable and the repaired experiment beats the strongest affordable alternative in value. |
| Infrastructure failure or interruption before a complete result | Quality is unresolved. Preserve partial work for diagnosis, reconcile cost, and repair/recover only if useful. |
| Valid result stops at a resource cap; progress remains near the stop | The tested allocation is insufficient to establish convergence. Consider a legal deeper or more efficient implementation; do not assume extrapolated improvement. |
| Valid result is flat, but the search did not finish a neighborhood, training is underfit, or a required component is absent | This prototype leaves a mechanism unresolved. Test the missing component or a complete affordable pipeline when evidence justifies it. Flatness alone does not establish maturity. |
| Completed local search, stable development learning behavior, or repeated negligible gains at suitable fidelity | The tested mechanism has plateau evidence. Consider a new representation, neighborhood, training signal, or route; local convergence is not global optimality. |
| A complete, applicable implementation loses under the intended limits and no supported rescue remains | Retire the tested mechanism at that scale/resource setting, retaining its result and reason. Broader rejection needs broader evidence. |

Use adapter-specific evidence already available: termination reason, actual work and objective progress for search; training/development curves and fit provenance for learned models; complete episode/horizon and constraint failures for policies. Small exact cases or an independently scored reference can reveal a defect, but do not prove large-case competitiveness. If evidence is missing, retain uncertainty; collect only diagnostics that can alter the next investment. Use development evidence, never confirmation errors, for this diagnosis.

Compare a lagging route's proposed **complete pipeline** against further refinement of the leader. Initial construction quality need not predict quality after local optimization; a model may require different preprocessing/training; a weak parent may have complementary errors. Test a credible combination or missing component rather than repeatedly polishing the same premature prototype. This does not give every route an automatic rescue trial: include implementation, full execution, downstream cost and remaining confirmation reserve, and defer when another action has stronger support.

Before a rescue, name the defect or missing capability, the observation that would justify continuation, and the rejection/stop condition. Count the changed implementation or resource setting as a candidate trial; unchanged diagnostic measurements still consume time/compute. A contest's per-candidate hard cap cannot be extended: improve work allocation or implementation within it. Training more can overfit, and searching longer can remain trapped; a recent progress trace is evidence for a test, not a promised gain. Compare any new result under the sealed full objective and intended resource constraints.

Keep the route's best representative, tested scope, unresolved mechanism and next investment decision alongside its promotion status. A route deferred because budget ran out is **untested or unresolved**, not empirically rejected. Reopen a retired mechanism only when a relevant dependency, implementation finding, resource setting or new evidence changes the reason for retirement.

## Select the Next Action

| Evidence or uncertainty | Action | Evidence needed to continue |
| --- | --- | --- |
| Only one family has been tried, with unclear fit | Explore a materially different route | A valid result, resource fit, and promising objective or complementary behavior |
| Low score with an unclear cause | Diagnose using case analysis, a profile, ablation, or small reference solution | A bottleneck or falsifiable explanation that suggests an affordable change |
| A valid lagging prototype leaves a credible mechanism unresolved | Compare a bounded repair/deepening or complete pipeline against the leader's next refinement | Cause/maturity evidence, a useful rejection test, and a full candidate within the intended limits |
| A component has a supported improvement mechanism | Refine that component | Matched evaluations that justify another variant or reveal a new testable mechanism |
| A route has evidence and unresolved high-impact mechanisms | Replace or deepen that mechanism | Full-objective gains or a consequential rejected hypothesis |
| Repeated tweaks produce negligible gains while structural alternatives remain | Return to the route map | A materially different affordable prototype or a documented reason to retire this route |
| Candidates have compatible, complementary strengths | Combine or select by regime | Improvement in the combined candidate's objective within its resource limits |
| Apparent gain is comparable to measurement variation | Repeat a matched comparison | Enough evidence to resolve the promotion decision |
| A currently applicable finite limit leaves only confirmation resources | Confirm the frozen shortlist | Validity and independent objective measurements for delivery |

Diagnostics consume time/compute; keep their results separate from candidate ranking. A correctness failure may justify a repair when the mechanism remains promising; an infrastructure failure gives no evidence about algorithm quality. Retry when a changed implementation or resolved prerequisite makes another attempt informative; do not repeat an unchanged failure without new evidence.

## Refine a Measured Component

When available resources support deeper search, use a targeted ablation, runtime profile, or small reference solution to choose a component worth refining. Within it, test an explanatory mechanism or coherent replacement per trial and use prior results to select the next variant. Include representation, solver encoding, search neighborhoods, features, and training signals where the task supports them; parameter changes are only one search action. Do not limit a route replacement to the incumbent's editable lines if its interface and rules permit a different implementation.

An ablation measures the current solution's reliance on a component, not its remaining improvement potential. Combine that evidence with a plausible improvement mechanism and evaluation cost. Keep the official evaluator fixed. An approximation used inside the candidate's search is itself a hypothesis and still needs confirmation on the declared objective.

Reallocate trials to another component or route when gains fail to reproduce, a limiting bound is reached, or remaining variants lack a credible benefit. A promising line need not be abandoned after one failed variant, and a familiar line does not earn extra trials merely because it is easy to edit.

## Explore, Refine, Combine

Use the route map to start with materially different solution families when affordable. Keep their parent IDs and best validated representatives; one route may excel at a different regime or later combine with another. This is a candidate portfolio and can be executed by one agent sequentially. Exploration is not finished merely because one quick-to-implement variant exists; deepening is not postponed merely to fill a prescribed number of routes.

After a mechanism works, inspect the updated code and remaining development errors to propose the next change; success does not trigger a parameter sweep. Compare candidates at documented evaluation fidelity. If promising gains from routes can coexist, propose a combination supported by their complementary behavior, then test it with all parent IDs. Gains need not add; evaluate the combination's objective, runtime and memory including selection or ensemble overhead. Use ensembling only when the submission format and metric support it.

For model ensembles, inspect complementary validation errors rather than selecting solely by individual rank. Reuse cached predictions only with matching sample IDs, split, preprocessing, model/configuration provenance, and metric. OOF predictions must exclude held-out samples and dependent groups from label-dependent fitting. Fit learned preprocessing within folds unless the contract permits transductive fitting; document any such use of held-out features. Choose a justified combination recipe from development evidence and confirm it independently; do not automatically sweep weights. A regime-specific algorithm selector must use features available at inference, not ground-truth outcomes.

For the supported scalar CSV interface, [the blend tool](data-model.md#construct-and-confirm-a-prediction-blend) constructs weighted candidates from compatible development evaluations and reapplies a frozen recipe by member name. When the two-parent decision needs error diagnostics, [the RMSE/MAE direction check](data-model.md#check-whether-a-two-parent-blend-has-a-useful-direction) can exclude segments with no strict development gain; case wins alone cannot decide this. It supplies no weight or practical gain estimate. Evaluate every blend with the declared metric, count each weight variant as a trial, and include all contributing models' inference cost. Freezing an algorithm selector's thresholds or a simulation policy mixture follows the same principle: selection settings are candidate parameters and cannot be retuned on confirmation evidence.

Reuse intermediates only when their dependencies match. A changed feature pipeline, split, model, or training configuration invalidates affected cached results even if output filenames are unchanged.

## Close the Feedback Loop

Every completed trial must inform the next implementation decision or an explicit stop. Close it with the result ID/path, comparable objective changes against its parent/current best, validity and cost, prediction status, and chosen follow-up. Use existing ledger/notes; no separate feedback document or extra measurement is required when the result already supports a decision.

| Feedback from development evidence | Follow-up using applicable resources |
| --- | --- |
| Implementation or infrastructure defect | Locate the defect and make a bounded repair when worthwhile; method quality remains unresolved |
| Measurement cannot resolve the comparison | Run the smallest diagnostic or matched repetition that could decide it; do not tune to noise |
| Eligible objective improvement | Update the best development candidate; test the newly limiting mechanism or a stronger affordable alternative |
| Valid weaker candidate, with supported missing capability or progress at its legal cap | Keep the incumbent; implement the supported complete pipeline or improve work allocation within hard limits |
| Repeated comparable negligible gains with maturity evidence | Reassess attainable score and the missing capability using [plateau recovery](plateau-recovery.md), then execute a complete alternative or a diagnostic that can choose it |
| Compatible complementary strengths | Implement and evaluate a combined candidate, including all inference/selection costs |

These choices depend on task evidence; they are not automatic quotas or proof of causation. Missing official score terms still require provisional comparisons and retained tradeoffs. Use [failure/maturity evidence](#decide-whether-to-repair-deepen-or-retire) when a weak score has several explanations.

Each successor must cite the feedback it acts on, identify its actual implementation target and expected observation, and retain a result link after execution. Check whether that expectation occurred before choosing another variant. A copied explanation followed by the same rejected configuration is not a feedback-driven change. Further tuning after confirmation requires fresh confirmation evidence.

For repeated runs using the archive helper, [bind the proposal and measured successor](iteration-trace.md) with `propose` and `record --proposal-id`. The proposal references actual parent code and development feedback; after implementation, the record attaches a new adapter result, observed feedback and prediction status. `trace` exposes pending actions and the real result chain. Use existing equivalent ledger links where available. Recording a plan cannot substitute for executing it in the current session.

At delivery, show the executed chain in a compact table: trial/result, measured comparison, feedback/action, successor/change and its result or stop reason. Best-so-far scores describe development selection; they are not independent confirmation. An unexecuted suggestion stays pending and cannot fill the successor/result column as a completed experiment.

## Learn from Evaluated Pairs

Use an informative matched comparison to change the next decision, not merely to narrate a score. Contrast candidate code/configuration, full-objective results, representative regimes, stopping behavior and actual cost. Reuse existing artifacts; extra profiling, ablation or measurements need a consequential question and budget.

Keep three layers separate in `research.md`:

| Layer | Useful content |
| --- | --- |
| Observation | Parent/candidate IDs and result paths; tested change, matched fidelity, gain/regressions and cost. State whether the prediction was supported, contradicted or unresolved. |
| Explanation | The proposed reason and an alternative explanation still compatible with the evidence. An improving trace may motivate work-allocation changes without proving wasted work caused the loss. |
| Next test or scoped lesson | A specific change, prerequisites, expected observation, rejection condition, and why it outranks the nearest affordable alternative; or a bounded lesson when no trial fits. |

If a prediction fails, revise its mechanism, applicability or expected observation; do not preserve the same claim behind a new candidate name. If the result is unresolved because of defects or uncertainty, retain that limitation rather than rewriting it as a method failure. If a change improves its parent but loses to the incumbent, retain both conclusions: local progress supports that tested implementation, while promotion still follows the full-objective comparison. Another refinement needs its own headroom and cost argument.

Carry only decision-relevant lessons forward, with task/metric, scale/resources, success and failure regimes, and linked evidence. Preserve contradictory findings instead of accumulating only successful advice. A learning entry should change an action, constraint or falsifiable prediction; skip generic reflections that do not. On resumption, check the lesson's dependencies before using it. On a different task, verify prerequisites and make a budgeted transfer test; prior gains are not promised gains. Learned-model examples concern experiment records, not online weight updates or permission to reuse held-out labels.

Examples of testable feedback are replacing search order when capped work still progresses, revising training signal when permitted labels/features leave systematic errors, or changing solver encoding when the measured scale bottleneck persists. These are task-qualified choices, not defaults. A candidate's internal objective approximation, schedule or training loss may change; the official evaluator and confirmation separation remain fixed. Continue the useful next test unless a currently applicable constraint or concrete blocker prevents it.

## Spend Evaluation Budget Where It Changes Decisions

Measure baseline costs and plan final verification. Record cumulative time/compute/cost and trials, including research, evaluator development, diagnostics, retries, training, full runs and confirmation. Include changed configurations, ablations, repairs and rejected candidates. Apply only currently applicable limits at their stated scope, with a measured verification reserve under a genuine finite constraint. When no cap applies, record that fact and continue without setting a numeric allowance or default round. A later user change/removal supersedes earlier optimization limits prospectively; old skill defaults never require renewed permission.

Use low-cost stages to reject invalid or clearly weak candidates. Before using a subset, reduced resolution, fewer training epochs, or shorter simulation as a score screen, check on reference candidates that it preserves useful ordering. Treat it as a screen, not the final score. Keep some full-fidelity comparisons on distinct mechanisms so a biased cheap screen does not eliminate all alternatives.

For paired scalar reference scores, [calibrate the proposed screen](screening.md) at the planned survivor count. Inspect inverted pairs and missed full-best candidates, not only overall agreement. Cutoff ties may increase survivors and cost; a successful analysis is not a screen-validity certificate. Prefer fewer credible full evaluations when affordable calibration cannot justify the shortcut.

If screening ordering fails, revise that screen and reevaluate affected candidates at comparable fidelity. Optimizing the development pipeline can buy more experiments without improving the submission itself; record which cost was reduced.

Evaluate the most promising candidates at full fidelity against the incumbent on matched development cases. Keep snapshots and results for other alternatives without automatically sending each to independent confirmation and package validation. Confirmation should resolve actual finalist selection or an explicitly requested validated alternative; use [verification stages](plateau-recovery.md#match-verification-to-the-decision) when that work dominates search. For noisy metrics, repeat to resolve a decision rather than choose the largest observed gain. Maintain validity, screening, and confirmation outcomes separately; a partial or failed run cannot establish a new best.

Distinguish execution/training randomness from finite-sample uncertainty and distribution mismatch. For fixed scalar predictions evaluated on exchangeable samples, [paired row/group bootstrap](data-model.md#estimate-paired-sampling-uncertainty) can estimate sensitivity to the validation sample. Declare independent units and sampling settings before interpreting the result; dependent groups stay together. For training randomness, rerun matched training seeds; for distribution shifts, confirm on task-appropriate independent scenarios. More draws on the same cached predictions do not resolve either issue. Report uncertain gains and retain promising alternatives without making significance a universal promotion gate, especially for exact deterministic contest objectives.

### Avoid Work That Cannot Change the Next Decision

Measure wall time by phase so research, setup, candidate execution, and diagnostic overhead are visible. Use [the decision card and resume routing](decision-loop.md) to recover only changed events and the current unresolved question. Reuse a verified contract, source finding, or baseline while its prerequisites and dependency hashes still match. Load only the relevant task/reference section.

Start with a cheap valid score comparison. Use detailed slicing, profiling, bootstrap, or repeated training for pairs whose outcome could change promotion or suggest the next mechanism. A clearly rejected candidate may need only its rejection evidence; a close finalist may justify a fuller analysis. These tools remain available when a weak route has informative complementary errors or another unresolved mechanism. Cache verified predictions and deterministic intermediates at their dependency boundaries; recompute only affected descendants after a change.

For CSV error analysis, use [summary output](data-model.md#diagnose-development-errors) when top cases and slice statistics resolve the question. It preserves full-split diagnostics while avoiding a redundant per-case export; retain referenced inputs and request the full table when other cases need inspection.

When a stage dominates cost, check whether it is needed for the current decision before optimizing its implementation. Improve loading, preprocessing, compilation, or score calculation when that buys useful trials. Validate equivalent outputs against the original path and include setup/verification cost in the efficiency claim. Keep required full-fidelity and final confirmation checks; reserve resources only under an actual finite constraint. Computational speed alone does not establish a score gain. For disturbed shared-machine measurements, use [timing recovery](plateau-recovery.md#make-timing-interpretable) rather than rerunning unaffected quality evaluations.

### Check Whether the Evidence Can Rank Candidates

When ranking uncertainty would change the next code/model proposal, resolve it using applicable resources. Small development sets, loss concentrated in a handful of cases, contradictory regimes or gains comparable to variation suggest a measurement experiment. Choose matched folds, training seeds, instances or episodes according to the task's uncertainty and available resources. Keep confirmation untouched. Preserve each repetition's score and compute the contract's aggregation; the best fold or luckiest seed is not the comparison score.

For learned models, declare internal folds in the training/development pool and fit every learned transform inside each fold. Compare the same pipelines on the same folds; specify pooled predictions versus mean fold scores because they can rank candidates differently. For algorithms and policies, use the same instances and environment seeds with the full declared resource limit. A cheap repeat can reveal unstable selection without changing either candidate.

Unchanged candidates repeated under a declared measurement protocol consume time/compute. Searching for a favorable seed is candidate selection, and tested seed variants are separate trials for accounting. A multi-seed model ensemble is also a new candidate with combined inference costs. Ensure resources remain for the mechanism actually selected when a finite constraint applies; do not silently add a large cross-validation campaign when it would displace a more informative test.

## Keep Search and Confirmation Separate

Freeze the development metric, evaluation split, case weights and final confirmation protocol before candidate search. Choose a split appropriate to deployment: group or time splits when samples are dependent, fresh instances for combinatorial tasks, and matched repeated seeds for stochastic simulations.

Keep repetitions of one candidate distinct from independent complete agent runs when assessing the skill itself.

Use development results to select a small final shortlist. Evaluate the frozen shortlist on the confirmation set using applicable resources. If its errors guide another edit, that set has become development evidence; document the reuse and arrange fresh confirmation where possible. Do not describe repeatedly inspected fixtures as unseen.

Record a `shortlist.json` before reading confirmation scores: finalist IDs and artifact hashes, reference/fallback, shortlist size, comparison protocol, and the decision rule for ties, uncertain gains, or ranking reversal. The rule should suit the task: a fixed exhaustive contest objective may permit direct metric choice, while estimated generalization needs its sampling limits stated. Apply the recorded rule instead of inventing a new one after seeing the outcomes. Confirmation can evaluate a frozen shortlist under that policy; tuning another configuration or expanding the shortlist from its feedback needs fresh evidence.

Report the best development result separately when confirmation is unavailable or disagrees. Full-data retraining produces final artifacts, not a new unbiased validation score.

Public leaderboard results can diagnose a mismatch with local validation, but repeated submissions can overfit the public set. Keep platform feedback and local evidence in separate records and respect submission authorization and quota.

## Promotion and Stop Decisions

Promote using the declared metric direction and official aggregation at matched fidelity. Do not reject a net score gain merely because it slows down or regresses in some cases, unless those are hard constraints. Conversely, an attractive mean on a convenient subset does not prove a gain on the actual objective.

Keep competition/user hard constraints separate from agent-chosen screening policies. A minimum 2% speedup or maximum 5% slowdown has no default authority; use a threshold only with a stated task, user or measurement basis. A screening cutoff can guide cost allocation without establishing that a smaller gain is false or a tradeoff loses official score. Revise unsupported policies prospectively before further development/confirmation, preserving past protocol versions and outcomes; never change a frozen delivery rule after confirmation to obtain a preferred winner.

If a full score cannot be calculated, preserve tradeoff candidates and label any selected incumbent as provisional under its stated heuristic. State which missing terms could reverse the choice. Do not invent a Pareto direction for a component whose effect on the score is unknown.

## Record Decisions and Recover State

Append planned and completed events under each trial ID in `trials.jsonl`; do not rewrite old outcomes. Before implementation include parent IDs, preceding feedback/result evidence, action/target, hypothesis, predicted observation, rejection test, planned fidelity and cost. After execution include candidate/configuration hashes, evaluation and comparison paths, validity/fidelity, objective kind/direction, actual cost, prediction status and the concrete follow-up or stop reason. Link the next trial back to that feedback and retain its actual change/result; reference immutable files instead of copying raw logs into the ledger.

At decision boundaries, refresh `next-action.md` using [the compact card](decision-loop.md#compact-decision-card). On resumption, reconcile its ledger checkpoint with new events; a missing or stale card is rebuilt from evidence. Partial, invalid, or interrupted runs remain diagnostic evidence. Reuse results only when their dependencies still match. Keep executing useful feedback-driven follow-ups without round renewal. When stalled, investigate a specific uncertainty or test a materially different supported mechanism. An unattended campaign uses a fresh-context review when no successor is apparent; a model's lack of ideas cannot end it. Stop for a user stop request, a currently applicable hard/resource limit, an observed unresolved blocker or verified task completion. Preserve cumulative costs, confirm/deliver as feasible and state the actual stop reason; historical default quotas are not stop reasons.
