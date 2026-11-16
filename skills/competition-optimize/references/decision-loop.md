# Resume and Choose the Next Action

Use this when continuing a run, recovering an interrupted trial, or deciding whether more research or diagnostics would help. The contract, append-only ledger, and immutable artifacts are the evidence; `next-action.md` is a replaceable summary. It neither grants extra budget nor establishes candidate validity.

## Recover Only What Changed

Read the sealed contract and the compact card first. Check the contract bytes against the card's hash and the ledger prefix against its checkpoint (byte length and SHA-256); these checks can read bytes without loading all events into model context. If both match, read only appended complete events and the evidence needed for the current decision. Verify the dependencies and validity scope of results you intend to reuse. A hash confirms identity, not training provenance or unchecked hard rules.

When a candidate archive is available, [retrieve `brief`](iteration-trace.md#retrieve-evidence-for-the-next-implementation) for matched best versions, recent failures, code locations and pending proposals in one read. Reuse the existing card's budget/contract facts; do not also reconstruct all candidate summaries. Choose a credible parent from the retrieved evidence rather than assuming the latest experiment won, inspect its relevant code, and continue the implementation loop.

[`inspect_run_resume.py`](../scripts/inspect_run_resume.py) performs the byte/syntax checks for any adapter's JSON-object events. For the first inspection, omit `--checkpoint`; it reads from the start and can save a new checkpoint file:

```powershell
python <skill-dir>/scripts/inspect_run_resume.py `
  --contract <run>/task-contract.json --ledger <run>/trials.jsonl `
  --max-events 20 --save-checkpoint <run>/checkpoint-001.json
```

Reconcile the returned events and referenced evidence before linking that checkpoint from `next-action.md`. On the next inspection, use it and save to another new file:

```powershell
python <skill-dir>/scripts/inspect_run_resume.py `
  --contract <run>/task-contract.json --ledger <run>/trials.jsonl `
  --checkpoint <run>/checkpoint-001.json `
  --max-events 20 --save-checkpoint <run>/checkpoint-002.json
```

With `has_more: true`, continue reading pages before deciding from the card. A saved checkpoint covers only returned events and intervening blank lines, so later events are not silently skipped. Complete event lines must end in a newline (UTF-8, LF or CRLF); a missing final newline, malformed object, duplicate JSON key, or non-finite number blocks inspection, including malformed events beyond the output page. Contract changes, prefix rewrites, truncation, and wrong checkpoint paths also return code 2 without saving a new checkpoint. Reconcile the defect before rebuilding; omitting a bad checkpoint does not make stale evidence current.

The tool reports checkpoint/JSONL integrity only. It does not infer trial budget, validate candidate artifacts, promote candidates, run commands contained in events, or alter the ledger/card. A new checkpoint is a proposed anchor; saving it does not mean the returned evidence has been reconciled. Source appends during inspection remain for the next page. Existing checkpoint files are never overwritten. Legacy cards with manual byte/hash fields can be checked manually once, then replaced with a file produced by this tool.

If the card is missing, its prefix differs, or the contract changed, rebuild relevant state from the ledger and artifacts. Contract changes invalidate dependent conclusions; they do not erase spent trials. No new event does not prove that an unfinished evaluation failed: inspect its process and output directory before retrying. A successful result missing a completed event can be reconciled only after verifying its completeness, dependencies, and hard checks, then appending the recovered outcome. A truncated final event or partial result remains unresolved; do not invent a completion or overwrite old evidence. Resolve a ledger write failure before appending more events; preserve damaged bytes and record the repair.

For reused prediction CSV scores, [comparison with `--truth`](data-model.md#compare-local-scores) can audit recorded scores against frozen truth and snapshots once before relying on them. The ledger inspector's `ready` status does not perform this check. Reuse a passed audit only while its recorded dependencies match; preserve unaffected artifacts and redo the specific invalidated work.

Reconcile trials/time/compute/cost, incumbent scope, alternatives, unfinished work and frozen shortlist. Establish the origin, scope and current applicability of any recorded limit: competition rule, actual resource availability, explicit user cap, obsolete skill default or agent estimate. Apply later user changes/removals prospectively and preserve consumed work. Missing records do not establish extra allowance under a still-applicable explicit limit; reconcile the gap conservatively.

`SKILL.md` imposes no default time, cost, trial or round cap. Continue from the same incumbent, history and cumulative costs without requesting another allowance or inventing a new round. Preserve old contracts and append the current limit policy when it changed; cancellation of an optimization cap does not change evaluation identity or rewrite prior results. If no applicable limit remains, record that fact and continue useful work. Reserve confirmation/packaging cost only under a genuine finite constraint. If confirmation feedback guides new search, it becomes development evidence and fresh confirmation is needed.

## Route the Current Decision

Choose the first applicable condition; this is routing within the current run, not a sequence to replay every turn.

Recover any still-relevant user ideas and their priority/test requests alongside the card. New input steers the next decision using [user-idea handling](score-search.md#turn-user-ideas-into-experiments); an explicit stop overrides routine routing. Reconcile an in-flight result before switching when it remains compatible, and retain superseded pending proposals with their actual status.

Route within the user's current requested scope. A request to learn a stronger method calls for its reasoning and design implications; an earlier optimization loop does not turn that request into another benchmark campaign.

| Current state | Next useful action | Exit condition |
| --- | --- | --- |
| An unfinished trial may already have evidence | Reconcile its artifacts/process and actual cost | Record verified completion, interruption, or failure before another trial |
| The user asks to understand a strong solution's thinking | Reconstruct its [strategy and dependencies](strategy-design.md#read-a-strong-solution-as-a-system), then compare actual capabilities with the incumbent | Explain the derivation and what it changes in our approach; execute migration only within the requested scope |
| Hard rules, score meaning, or comparison dependencies are unresolved | Resolve the specific contract/measurement defect | A trustworthy comparison path or an explicit provisional limitation |
| The current route has no concrete useful follow-up | Re-derive the formulation or resolve the specific missing evidence; use a fresh-context review in an unattended campaign | Retiring a route does not complete the campaign |
| The user requests stopping, a genuine finite constraint leaves only confirmation resources, a concrete blocker prevents further work, or task completion is verified | Freeze/confirm the shortlist, or deliver if confirmation is done | State the stop reason, apply the sealed delivery rule and preserve remaining uncertainty |
| No valid credible baseline exists | Establish one affordable reference | Validity, objective, and measured cost for subsequent comparisons |
| Comparable refinements have weak returns, proxy rankings conflict, or verification dominates search | Apply [plateau recovery](plateau-recovery.md) to choose a structural prototype or consequential diagnostic | Attainable score scope, the missing capability, and an executable next action; confirmation/packaging only when needed for selection/delivery |
| Ranking or mechanism uncertainty prevents choosing a trial | Run a targeted diagnostic or matched repetition | A stated result changes promotion or identifies a testable mechanism |
| An affordable falsifiable mechanism is ready | Compare its route with the strongest affordable alternative, then execute the chosen test | Reject, advance to matched full fidelity, or identify missing evidence |
| Missing knowledge prevents a viable mechanism | Search for that specific gap | A source-backed test with prerequisites, or retire the route |

For an LLM/agent entry, route the uncertainty through [its mechanism guide](llm-agent-competitions.md#choose-the-layer-from-evidence). Distinguish whether correct answers are absent from sampled generations, present but not selected, lost to parsing/timeouts, or invalidated by later interaction. [Cached vote replay](inference-vote-replay.md) can inform a fixed-sample selection or stopping proposal; changed models, generation or tool policies require execution through the task adapter. Keep the report path/hash in the proposal or decision card and retain the original measured candidate as the comparison control.

Resolve a rules/scoring defect using applicable resources; do not report an invalid comparison as confirmed. An infrastructure failure warrants a targeted repair when useful, not a fresh algorithm conclusion. Record repair variants and the time/compute of unchanged reruns under the declared protocol; count them against a trial cap only when one currently applies.

Before execution, assess which observation changes the next decision, which evidence can be reused, and the cost of implementation + execution + analysis + possible full-fidelity follow-up. Check that cost and any confirmation/packaging reserve against applicable finite limits only; no numeric allowance is needed otherwise. Use measured costs where available and label estimates. No plausible decision change means defer that action. Full-fidelity promotion, provenance checks, and confirmation remain necessary even when intermediate work is cached.

For score-seeking runs, recover the task formulation, inspect the pertinent implementation changes, and retrieve the [route comparison](score-search.md#compare-routes-before-choosing-variants) and candidate archive. Recover tested maturity/resource settings and unresolved mechanisms: promotion rank alone does not determine investment. Use [task/code/history proposal guidance](score-search.md#propose-from-task-structure-code-and-history), [archive and route switching](score-search.md#candidate-archive-and-route-switching) and [failure evidence](score-search.md#decide-whether-to-repair-deepen-or-retire) to choose the next implementation. Revisit the formulation when a new strong source or repeated adjacent patches warrant it; an ordinary resumption can reuse it. Preserve the archive and route map across continuation. Resumption does not start a parameter campaign.

If the run uses the JSONL helper, inspect `candidate-archive.jsonl` with `candidate_archive.py summary` before reading old candidate prose. Run `decide --append` only after the latest result and feedback have been reconciled; a mechanically emitted route suggestion is evidence for the card, not a promotion decision. A duplicate-fingerprint error blocks an unchanged implementation: change the code/configuration, or give a necessary repetition or changed evaluation premise an explicit `--reuse-reason`. That exception does not make it a new mechanism or expand the budget. Existing equivalent archives need no migration.

Keep rejected hypotheses with their mechanism, prerequisites, and rejection evidence. Recover the applicable [comparison lessons](score-search.md#learn-from-evaluated-pairs), including contradicted predictions and local improvements that did not beat the incumbent. They should identify the next test or constraint, not replace artifact checks. Reopen a rejected hypothesis when a dependency, implementation diagnosis, or new source changes that evidence. A new filename or another request to continue is not new evidence. After a failure, revise the hypothesis or switch route; do not regenerate the same configuration through repeated broad searches.

After a trial is reconciled, apply [the feedback loop](score-search.md#close-the-feedback-loop) and execute the next useful action. A retired route returns to this decision routing; a completed evaluation is not an automatic confirmation, packaging or task boundary. When resuming, recover the last feedback and whether its successor was actually implemented; a pending suggestion is not a completed iteration.

With archive proposal links, use [`trace --recent 8`](iteration-trace.md#resume-and-deliver-the-actual-chain) to recover the displayed execution chain and all pending IDs. Check existing processes/artifacts for pending actions before retrying; attach a verified result or record a specific stop. Old trials need no retrospective proposal reconstruction. The helper checks linked identities, while budget, actual code semantics and confirmation still use the existing run evidence.

## Compact Decision Card

Refresh `<run>/next-action.md` after a decision or before a handoff, not after every tool call. Keep only facts needed for the next action and link to details; it is disposable and never replaces ledger events. The checkpoint covers complete JSONL events through the recorded byte offset. Later events must be reconciled before acting. Do not checkpoint a partial final line.

Use the fields relevant to the task; this is a copyable example, not a required adapter schema:

When an archived proposal already contains the code basis, change and validation, the card needs its proposal ID/path and current state rather than another copy of those fields.

```markdown
# Next action

Contract: task-contract.json; SHA-256: <contract hash>
Ledger checkpoint: <checkpoint file, or verified byte length + prefix SHA-256>; last event: <trial/event/time>
Incumbent: <ID>; scope: <development/provisional/confirmed>; evidence: <result and checks>
Alternatives: <IDs and the uncertainty worth preserving>
Routes: <current/alternative routes; tested maturity/resource setting; unresolved mechanism; research.md section>
Resources: <cumulative time/compute/cost and trials; applicable limit origin/scope and remaining, or no self-imposed cap>; confirmation/packaging: <planned cost; reserve only under a finite constraint>
Unfinished: <trial ID and output/process, or none>
Frozen shortlist: <path/hash, or not yet frozen>

Next action: <one action and parent IDs>
User idea, when applicable: <short original or source; suggestion/test/requirement; interpretation; pending proposal/result or deferral reason>
Feedback source: <trial/result path; measured comparison vs parent/best; validity and cost; prediction status>
Archive update: <candidate ID/fingerprint/status; retained route; failure mechanism or unresolved opportunity>
Reconnaissance: <code path, relevant history, hashes checked; reused evidence and unresolved gap>
Code basis: <current snapshot/hash; relevant function/component and limiting behavior>
Related history: <pertinent successful/failed trial IDs; lessons and scope; why this differs from rejected attempts>
Optimization proposal: <specific code/pipeline change, mechanism and parent; expected observation; why this change now>
Route decision: <exploit/explore; why this route now; switch trigger>
Quality gate: <interface/rules/evaluator/artifact/screen checks and outcome>
Evidence to reuse / invalidate: <paths, dependency hashes, affected descendants>
Execution: <command or implementation target, stage/fidelity, resource cap, total cost estimate>
If rejected / promising: <next branch, including full-fidelity cost when needed>
```

An old run needs no migration: rebuild a card only when resuming it. A tiny completed run may have nothing unresolved beyond delivery; do not create a new hypothesis queue just to fill the template. Source details stay in `research.md`, candidate history in `trials.jsonl`, and final selection in the frozen shortlist and delivery evidence. Record only aggregate confirmation outcomes needed for the delivery rule, never tuning suggestions extracted from confirmation errors.
