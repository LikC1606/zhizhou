# Organize parallel research when it helps

Delegate only when delegation is exposed and permitted in this session. A useful independent assignment has a concrete question and an inspectable output, such as a source survey with hypothesis mapping, a counterexample search, an exact library declaration, or a separately checked candidate. Account for coordination and duplicated work; do not create tasks solely to keep agents busy.

Give an investigator the original statement and enough definitions and environment context to understand the assigned question. For an independent review, avoid supplying the answer it is expected to endorse. Retain disagreements and check the supporting artifacts before deciding what to integrate.

## Persistent proof-writing team

When the host exposes `theoremos_team`, Lead chooses the decomposition, assignments, route changes and adoption decisions. Children have isolated writable worktrees, the same pinned Skill and their own native threads. A later assignment continues that child's thread and saved sources. All agents share the run's time, turn and token allowances. The host enforces source ownership, process isolation, persistence and independent proof checks.

Use the tool's `operation` field:

| Operation | Caller | Arguments and result |
| --- | --- | --- |
| `spawn` | Lead | `agentId`, `message`: create a child and queue its first assignment; returns a task ID. |
| `assign` | Lead | `agentId`, `message`: queue follow-up work for an existing child. |
| `message` | Any member | `agentId`, `message`: save an advisory message to `lead` or a child; notify its current session when available. |
| `poll` | Any member | Optional `after` cursor: receive addressed events, worker/task summaries, delivery IDs and adoption status immediately. |
| `wait` | Any member | `after`, optional `timeoutMs` from 1 to 30000: wait for addressed events, then return the same snapshot as `poll`. |
| `inspect` | Any member | `deliveryId`: read a checked delivery's exact declarations, commit, source digest, imports, source excerpts and proof evidence. Excerpts report truncation. |
| `submit` | Child | `summary`, `declarations`: nominate the current assignment's exact declarations for checking after returning. |
| `adopt` | Lead | `deliveryId`, optional `targetId` (default `lead`): request checked integration into Lead or an idle child. |
| `stop` | Lead | `agentId`: prevent further assignments and request interruption of an active child; shutdown finishes asynchronously. |

`spawn` and `assign` queue work without waiting for its completion. Use the returned cursor in the next `poll` or `wait`; each result can arrive while other children continue. Messages and completion summaries are advisory. Use `inspect` to assess a proof delivery before deciding whether to adopt it. A saved result is available even after its producer receives another assignment.

A child submitting Lean work supplies 1–32 declarations, each with `file`, fully qualified `name` and complete closed `type`; optional `description` and explicit `premises` preserve its interface. List every changed declaration in the delivery. Preserve frozen statements and source ownership; an unchecked source change is not transferable evidence. Save sources and research notes, call `submit`, then return. Its `pending-writer-stop` response records the request; it does not assert that checking passed. The host confirms shutdown, freezes actual source bytes and checks the submitted declarations before publishing a delivery ID. Read failures from the task/event feedback and correct them through a later assignment.

Draft sources from a deferred or rejected delivery remain part of the next submission. List their changed declarations as well as the new corrections; only a successful delivery advances this source baseline. A child with undelivered source changes must finish publishing them before receiving a peer adoption, so that integration preserves its draft's identity.

For adoption into Lead, call `adopt` and return to release your writer. The host freezes current sources, checks the selected delivery against that version, integrates it, and continues the saved Lead thread with feedback. Adoption into a child requires that target to be idle, with no active writer; it can then receive a follow-up assignment using the integrated declarations. A conflict or failed recheck is reported to Lead. Do not copy a peer's mutable files or edit another worktree or host state to bypass this protocol.

Keep organizing useful work while children are active. On host recovery, an interrupted assignment retains its sources and thread but needs an explicit new assignment to continue. Pending checking and adoption retain their saved identities. An unconfirmed writer stop prevents further writing or acceptance in that workspace.

A checked local delivery or completed adoption does not establish the original problem. The host independently checks every frozen original target before whole-problem acceptance.

## Other delegation modes

When only `theoremos_investigate` is exposed, use its bounded `questions` array for read-only investigations. That call waits for all results; investigators do not retain proof-writing assignments. The primary researcher integrates any useful findings within its own source permissions.

Without a supported team interface, use read-only investigations or separately isolated candidate workspaces within the actual host capability. Do not grant broader permissions, edit run state or treat a completion message as proof acceptance. An unavailable child tool is not a reason to fabricate a parallel workflow; built-in spawn/fork remains disabled in these host-managed modes.
