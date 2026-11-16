# Cooperative delivery

Use this reference only for a host-assigned cooperative role. The model chooses the mathematics; this document describes delivery interfaces. Read [shared rules](#shared-rules), then the section for [Lead](#lead-plan), [proof work](#proof-delivery), [research](#research-delivery) or [independent review](#independent-review). Read [gap and check reports](#gaps-blockers-and-checks), [required decisions](#required-lead-decisions) and [feedback](#feedback-and-corrections) when the current assignment calls for them.

## Shared rules

The current assignment and `.scratch/theoremos-help.md` provide exact paths, interfaces, versions, nonce and feedback. They supersede old dispatch values. Use only exposed tools within current permissions. The host owns task assignment, isolation, integration, approvals and budgets; create additional agents only when it permits them.

Append complete newline-terminated JSON events to the current delivery log. A missing log is normal; create it by appending. Preserve earlier events. In an assignment-scoped task log, omitted `id`, `taskId`, `taskDigest` and `kind` are supplied by the host (`kind` defaults to `progress`); supplied task identity must match the assignment. Explicit event and task IDs use `[A-Za-z0-9_-]{1,64}`.

Edit only assigned source paths. Preserve other seed proofs and frozen declaration interfaces, kinds, imports, options, scopes and source order. A goal cannot depend on a later original goal in the same file; put a shared helper before its consumers instead of moving original declarations. Do not edit host state, `COOPERATION.json`, generated help, Skills, configuration or receipts. Do not run `git add` or `git commit`; the host freezes saved sources. Notes, checkpoint receipts, local diagnostics and peer messages remain evidence rather than proof acceptance.

## Lead plan

Leave Lean sources unchanged and return a plan without running Lean diagnostics; assigned workers execute proof and check tasks. Publish one JSON line to the current Lead delivery log:

```json
{"kind":"plan","baseVersion":"CURRENT_BASE_VERSION","dispatchNonce":"CURRENT_DISPATCH_NONCE","summary":"route and consumers","tasks":[]}
```

Replace dispatch values from the assignment; omit `dispatchNonce` if none is supplied. Replace the empty `tasks` array with the complete graph. The first plan covers every original target exactly once. Keep checked task contracts and active unrelated assignments stable. Publish once per dispatch, save concise route notes and return promptly without polling approval or copying the published graph into other responses.

When returning without live publication, save the graph in one `math-plan` JSON fence in worktree-root `RESEARCH.md`. Include any [required decision fields](#required-lead-decisions) in the same plan object.

For `idleWorkers` with `m3-no-ready`, `dependency-blocked` or `m5-no-selection`, inspect M3 readiness, role/owner and saved-assignment pins. Publish an executable revision, name the concrete running dependency when waiting, or explicitly pause the route. Returning an unchanged accepted graph does not resolve that continuous idle episode.

### Task interfaces

Every task has `id`, `kind` and `objective`; `dependsOn` defaults to `[]`, `revision` to `0`. Plan `status` is `active`, `paused` or `stopped` (omission means `active`), never the host's `executionStatus`.

| Kind | Deliverable |
| --- | --- |
| `goal` | Exact original `theoremName` and owned `proofPath`; the host infers its frozen type and path from the original target. |
| `lemma` | `theoremName`, owned `proofPath` and actual full closed Lean `type`, including parameters and hypotheses. `proofPath` may be omitted only when one Lean file is owned. |
| Untyped `research` or `sketch` | Advisory findings; no proof deliverable. A typed research/sketch task is normalized to `lemma`. |

Typed declaration final name components must be unique and must not reuse frozen declaration names. Do not put placeholder types in a plan. An audit objective cannot replace a goal/lemma's assigned proof; use an advisory task for an audit.

Proof `dependsOn` names actual typed inputs. Advisory dependencies are inspection inputs rather than proof premises. Only untyped research/sketch may use `consumerGoalIds` to name original goals; connect typed helpers through consumer dependencies or [proof routes](#optional-task-forms).

Optional task metadata includes `premises`, `informalProof` (at most 2000 characters), `citations` (at most 8 references, 300 characters each), `researchSource` (`mathlib`, `verified-library`, `public-literature`; advisory tasks only), and `reviewScope` (`feasibility` or `final-candidate`; advisory tasks only). Final-candidate review waits for freshly checked original goals. Blueprints and citations do not change proof contracts. For statement-meaning review, use `statementReview:true` with `informalStatement` and the assignment's review interface.

Optional `groups` carry `id`, `objective`, `status`, `revision`, `engineerId`, `maxTurns` and `maxConcurrent`. Tasks use `groupId` and `sharing` (`group` or `problem`); cross-group inputs require problem sharing. Use `ownerId` only for an intentional reservation. Omitting it does not release an existing assignment. Do not copy host-owned capacity explorations or pending-check tasks into the editable graph or use their IDs as proof premises.

### Revisions

Revise the accepted graph with top-level fields instead of repeating it:

```json
{"kind":"plan","baseVersion":"CURRENT_BASE_VERSION","dispatchNonce":"CURRENT_DISPATCH_NONCE","summary":"change and reason","upsert":[],"remove":[]}
```

An existing task upsert merges only supplied fields; `null` deletes a field. Changing `kind` replaces the whole task, and a new ID requires its complete definition. Unlisted tasks, groups and proof routes remain. Supplying `groups` or `proofRoutes` replaces that entire list. Do not mix `tasks` with `upsert`/`remove`. Decision-only revisions may use `upsert:[]`.

Use the current accepted base and dispatch; stale revisions are rejected. Revise a contract only for a mathematical change: changing prose or `revision` is not new input and can invalidate saved work. Read the host-synced graph by task ID instead of rewriting it wholesale.

### Optional task forms

- **Conditional proof:** `conditional:true`, or `assignment.connectionCheck`, permits only its fixed typed proposition-lemma inputs. Reference those names without adding stubs, axioms or assumptions. The host supplies them as hypotheses in a disposable projection; full-file diagnostics may still show missing inputs. A successful conditional check proves sufficiency only; the input obligations remain.
- **Definition:** `kind:"lemma",declaration:"definition"` with its Lean `type` requires a checked definition body before consumers use it. It cannot also be conditional or a statement-review task. Record its intended meaning in `objective`; add a same-file typed sanity lemma characterizing that meaning. List the definition in consumers' dependencies when their types mention it.
- **Finite family:** add `family:{lo,hi,chunk,predicate}` to a proposition lemma, where `lo` and `hi` are nonnegative integers, `lo < hi`, `chunk >= 1`, and `predicate` names a declared `Nat → Prop`. At most 256 members are supported; leave room in the parent ID for the derived suffix. The host sets `∀ i : Nat, lo ≤ i → i < hi → predicate i`, derives `ID_c0`, `ID_c1`, … and makes the family conditional by default. Edit the parent, not derived members; a member proves only its own range. Consumers depend on the parent, which the host assembles and checks from its members.
- **Proof route:** `proofRoutes` entries are `{id,targetTaskId,prerequisiteTaskIds,closingTaskId}`. The target is an original goal; prerequisites are typed lemmas; the closing task is a proposition lemma, not a definition. Its transitive dependencies must cover every route prerequisite. Prerequisites within a route are conjunctive; routes to one goal are alternatives, with ordinary target dependencies still additional. A checked closing lemma enables an original-goal attempt; closing the route also requires strict original checking and an actual proof reference to that lemma. Group scope and acyclicity still apply.

## Proof delivery

Save the assigned exact declaration in its allowed proof file, then append:

```json
{"kind":"ready","summary":"saved assigned proof"}
```

Omit `commit` and `targets`; the host selects and freezes the source for the assigned declaration. Stop writing and return. Natural return also submits saved work. Read `COOPERATION.json.proofReadyRecords` for the specific result. A new attempt after failure uses a new event ID; an unchanged submission is deduplicated. Unconfirmed writer shutdown causes host quarantine rather than acceptance.

Unfinished typed work may deliver an intermediate [research finding](#research-delivery) without changing its proof obligation. A progress event such as `{"summary":"current result and remaining gap"}` does not complete or accept the proof.

## Research delivery

Save findings and reproducible evidence in `RESEARCH.md`, then append:

```json
{"kind":"research","finding":{"summary":"argument, assumptions and remaining gap","conclusion":"inconclusive","needsDecision":true,"evidenceRefs":[],"remainingObligations":[],"lemmaRequests":[]}}
```

Choose one `conclusion`: `supporting`, `refuted` or `inconclusive`. Use `refuted` only for a concrete refutation of the scoped claim; failed search or an unknown inference is inconclusive. `summary` is nonempty; optional `premises` and `remainingObligations` are string arrays. Set `needsDecision:true` for a route decision. Findings remain advisory.

Put `lemmaRequests`, `mathematicalGap`, `blockers`, `checkOutcome` and `replacesReceipt` **inside `finding`**. Lemma requests need new IDs and complete typed task definitions (`kind:"lemma"`, objective, theorem name, closed type, owned proof path and dependencies) in the same route group. They become proof assignments only after Lead adoption; proposals do not authorize source edits.

Advisory research/sketch leaves Lean files as in the assignment seed on delivery. A typed finding that relies on changed supporting Lean sources must bind those sources: outer event `sources` maps **every currently allowed owned, nonfrozen Lean path** to its complete UTF-8 content, at most 1,000,000 bytes total. Serialize from files. Exact allowed paths come from the current assignment. Without `sources` or `commit`, the finding is bound to its seed; a supporting immutable `commit` must descend from that seed. These two fields are mutually exclusive. The normal flow uses host source snapshots, not worker-created commits.

If exposed by current help, `theorem-os research-observe --worktree WORKTREE --finding FINDING_FILE [--probe LEAN_FILE] [--snapshot-sources]` validates and records this report. `--finding` takes a file containing the finding object, not inline JSON or the outer delivery event.

## Independent review

For `action.kind:"review"`, leave Lean sources unchanged. Compare the fixed candidate with the frozen original declarations, assumptions and matching Lean evidence. Run diagnostics only to resolve a concrete question that can affect the verdict. Save one final JSON object in `RESEARCH.md`, then return:

```json
{"verdict":"accepted","summary":"decisive evidence","evidenceRefs":[]}
```

Choose `accepted` or `changes_requested`; identify the exact change for the latter. The verdict does not replace independent host checking or final S3 acceptance. A task with `reviewScope:"feasibility"` instead uses the advisory research/check-outcome interface. Dedicated statement reviews follow their assigned interface.

## Gaps, blockers and checks

Use these fields when reporting a scoped unresolved inference; they do not refute the original problem or create proof premises. A research event nests them in `finding`; a progress event may carry `mathematicalGap` or `blockers` at the top level.

### Mathematical gap

```json
{"consumer":{"taskId":"VISIBLE_ORIGINAL_GOAL","taskDigest":"CURRENT_GOAL_DIGEST"},"previousGap":"prior inference","reduced":"established result","remaining":"unresolved inference","evidenceScope":"assumptions and scope","reconsiderWhen":["new relevant input"]}
```

Copy the consumer's exact current visible goal identity. Optional `previousDeliveryId` must be a `COOPERATION.json.mathematicalGaps[].deliveryId` for that original goal, not an arbitrary delivery. Optional `nextCheck` describes an investigation:

```json
{"action":"feasibility","objective":"specific inference to test","expectedEvidence":"evidence that can decide it","targetTaskId":"VISIBLE_TASK"}
```

Actions are `feasibility`, `apply-lemma` or `construction-check`. Target a visible planned task, not a host-generated advisory check. Optional executable application/proof-search inputs follow the exact tool schema in generated help.

### Blocker

```json
{"mechanism":"stable mechanism","scope":"exact inference","evidenceRefs":[]}
```

Optional `blockerId` refers to an existing blocker for this task/route. Optional `reopenOn` is an array of `{kind:"contract-changed"}`, `{kind:"environment-changed"}` or `{kind:"dependency-checked",taskId}` objects. Task references must lie inside the declared dependency cone or assigned route. Omit conditions to use host defaults. Repeating the same basis can park that local task. Renamed queries, prose or revision numbers are not new inputs; elapsed time is not a mathematical failure or deadline.

### Assigned check outcome

Complete a pending host check with `finding.checkOutcome`:

```json
{"checkId":"ASSIGNED_CHECK_ID","conclusion":"inconclusive","summary":"scoped result","evidenceRefs":[]}
```

Use the pending check for this assignment's current target, consumer, task and versions. Choose the same conclusion as the containing finding; unknown remains inconclusive. Do not invent check IDs or turn a check into a proof dependency.

## Required Lead decisions

When current feedback requires these fields, include them in the **same plan/revision object**. Use the presented IDs; do not manufacture decision obligations.

- **`researchDecisions`:** answer each shown delivery with `{deliveryId,outcome:"adopt",taskIds:[...],reason}`, `{deliveryId,outcome:"source",sourcePaths:[...],reason}` or `{deliveryId,outcome:"decline",reason}`. Adoption requires newly added or substantively changed tasks matching the proposed contract. Source adoption is final only after changed owned Lean sources have actually been merged; read-only Lead planning cannot manufacture that state. Decline needs a concrete mathematical reason.
- **`progressReview`:** `{id,reason,nextChecks:[{action,objective,expectedEvidence,targetTaskId}]}`. Checks must use active available tasks/groups and serve every reviewed original goal through actual dependencies/routes or advisory `consumerGoalIds`.
- **`nextCheckDecisions`:** `{checkId,outcomeDeliveryId,action,reason,counterEvidenceDeliveryId?}` with action `continue`, `revise` or `stop`. Continuing after a refutation needs another current supporting check for the same target and consumer with retained evidence. Otherwise make a substantive revision, request a new independent feasibility check or stop; rewording the objective does not answer the refutation.
- **`goalPath`:** `{adopt:[candidateId],decline:[{taskId,reason}]}` for the presented stalled-frontier candidates. A mechanical candidate can be applied by ID; other adoption requires its actual corresponding task/group change. Planning candidates are not proof evidence.

## Feedback and corrections

Read the current assignment's referenced `COOPERATION.json` records and feedback before continuing. A matching task digest does not mean its inbox is unchanged. Retrieve referenced evidence before using it; unavailable evidence supplies no premise.

A delivery's `summarySource` points to its full finding in the context manifest. If that section was omitted for budget, retrieve notes using `savedSource.commit` and `savedSource.notesPath`; omission does not mean no result was saved. A "Saved Lead draft pending integration" similarly retains interrupted source work at a fixed commit. Inspect it with `git show COMMIT:PROJECT_RELATIVE_PATH`, then recover useful declarations through typed tasks against current canonical sources, preserving integrated proofs. Drafts still require normal host checking.

For intake corrections, inspect **every** `deliveryReceipts` row scoped to this worker, task, task digest, seed, assignment and environment with status `needs-correction`. Match any supplied receipt index/count/digest. Append a complete corrected research event with `finding.replacesReceipt` set to that receipt ID; preserve the log and earlier evidence. If the correction is rejected, replace its new receipt. Each independent rejected submission needs its own correction; only the verified replacement chain is resolved.

Correcting an earlier **valid** finding is different: update the active note's conclusion, cite the immutable old commit/finding digest, identify the bad inference, and retain corrected evidence and remaining gap. Publish a new `needsDecision:true` finding; Lead then revises or rechecks the affected route. Do not rewrite archived findings.

### Delivered guidance

Only for guidance actually delivered to this assignment, include top-level `guidanceDecisions`, outside `finding`:

```json
[{"guidanceId":"DELIVERED_ID","status":"accepted","reason":"specific reason","evidenceRefs":[]}]
```

Status is `accepted`, `declined` or `needs-info`. Evidence references are typed: `{kind:"task",id,version}`, `{kind:"plan",version}` or `{kind:"edit",id}` for an applied edit. The same status/reason can later add evidence references. Lead includes these decisions in its one plan publication/revision, or unpublished `RESEARCH.md` plan; after publication, guidance-only metadata belongs in the final response rather than a competing plan. Guidance stays advisory and does not itself apply edits, change ownership or accept proofs.
