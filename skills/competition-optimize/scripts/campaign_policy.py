"""Pure turn decisions for an unattended campaign.

The driver owns evidence acceptance, sealed requests, processes and persistence.
This module returns schema-v2 state updates without mutating its inputs. Work
selection and context lifetime are independent; a fresh context can keep working
on the same frozen measurement plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from campaign_search import (
    CampaignEvidence, comparison_review_due, execution_review_due,
    observed_implementation, review_due,
)


@dataclass(frozen=True)
class TurnPlan:
    updates: dict[str, Any]
    fresh_context: bool
    context_refresh_reason: str
    review_requests: dict[str, Any]


@dataclass(frozen=True)
class TurnOutcome:
    evidence: CampaignEvidence
    appended_events: list[dict[str, Any]]
    archive_delta: Mapping[str, int]
    receipt: Mapping[str, Any] | None
    now: float


@dataclass(frozen=True)
class _Work:
    mode: str
    next_action: str
    reason: str = ""
    reviews: dict[str, Any] = field(default_factory=dict)


class CampaignPolicy:
    """Decide from accepted history; applying returned updates belongs to callers."""

    def _work(self, memory: Mapping[str, Any], facts: Mapping[str, Any]) -> _Work:
        progress, health = facts["objective_progress"], facts["execution_health"]
        continuity, plan = facts["comparison_continuity"], facts["measurement_plan"]
        action = memory["next_action"]
        if health["needs_attention"]:
            if execution_review_due(health, memory["execution_review_checkpoint"], memory["failure_review_window"]):
                return _Work("repair", action, "execution_stagnation", {"execution": {
                    key: health[key] for key in ("execution_attempts", "last_scored_candidate")}})
            return _Work("repair", action)
        if plan:
            return _Work("measure", (
                f"Complete frozen measurement plan {plan['plan_id']} using its next paired run; "
                "retrieve exact slots and decision rule with candidate_archive.py measure-status"))
        if comparison_review_due(continuity, memory["comparison_review_window"]):
            return _Work("measure", (
                "Inspect the isolated contracts and remeasure a trusted reference and candidate under an existing "
                "legal common development contract; judge gains only after complete comparison identities match"),
                "comparison_isolation", {"comparison": {
                    "distinct_observations": continuity["distinct_observations"]}})
        conflict = facts["repeat_conflict"]
        if (conflict and conflict["signature"] not in facts["measurement_signatures"] and
                memory["repeat_review_checkpoints"].get(progress["comparison_key"]) != conflict["signature"]):
            return _Work("measure", (
                "Inspect the two implementations and the conflicting repeated result; predeclare a matched "
                "task-specific measurement protocol, then execute its next decision-changing observation"),
                "repeat_disagreement", {"repeat": {
                    "comparison_key": progress["comparison_key"], "signature": conflict["signature"]}})
        previous = memory["strategy_review_checkpoints"].get(progress["comparison_key"])
        if review_due(progress, previous, memory["stagnation_window"]):
            return _Work("rethink", (
                "Compare the historical best with recent nonimproving implementations and other archived branches; "
                "reassess the remaining capability gap and execute an informative successor"), "objective_stagnation")
        # Repair and measurement are derived from current evidence, not durable
        # requests that survive after a failed invocation has resolved them.
        mode = memory["next_mode"] if memory["next_mode"] in {"execute", "rethink"} else "work"
        return _Work(mode, action, "strategy_review" if mode == "rethink" else "")

    def prepare(self, memory: Mapping[str, Any], evidence: CampaignEvidence) -> TurnPlan:
        """Stage a new turn; neither review nor exposure is acknowledged here."""
        facts = evidence.signals(memory["comparison_review_checkpoint"])
        work = self._work(memory, facts)
        reason = work.reason
        if not reason:
            if (memory["session_id"] and memory["session_checkpoints"] and
                    memory["session_turns"] >= memory["session_checkpoints"]):
                reason = "scheduled_rotation"
            elif not memory["session_id"]:
                reason = "session_recovery" if memory["turn_number"] else "initial"
        updates = {key: facts[key] for key in
                   ("objective_progress", "execution_health", "comparison_continuity")}
        updates.update(next_mode=work.mode, next_action=work.next_action)
        if reason:
            updates.update(session_id=None, session_turns=0, context_refresh_reason=reason,
                           context_refreshes=memory["context_refreshes"] + bool(memory["turn_number"]))
        reviews = dict(work.reviews)
        progress = facts["objective_progress"]
        if work.mode == "rethink" and progress["best_candidate"]:
            reviews["strategy"] = {key: progress[key] for key in
                                   ("comparison_key", "best_candidate", "comparable_implementations")}
        return TurnPlan(updates, bool(reason), reason, reviews)

    def accept(self, memory: Mapping[str, Any], turn: Mapping[str, Any],
               outcome: TurnOutcome) -> dict[str, Any]:
        """Account for accepted evidence separately from successful delivery.

        The driver classifies receipt success after validating the durable exit
        and archive. Failed invocations can contribute verified archive events,
        but cannot acknowledge any card or review from their sealed request.
        Time is supplied by the driver; this method performs no I/O.
        """
        facts = outcome.evidence.signals(memory["comparison_review_checkpoint"])
        updates = {key: facts[key] for key in
                   ("objective_progress", "execution_health", "comparison_continuity")}
        idle = 0 if outcome.archive_delta["executed_implementations"] > 0 else memory["turns_without_implementation"] + 1
        updates["turns_without_implementation"] = idle
        receipt = outcome.receipt
        if receipt is None:
            retry_memory = dict(memory)
            if memory["failures"] + 1 >= 2:
                retry_memory["next_mode"] = "rethink"
                updates["session_id"] = None
            updates["next_mode"] = self._work(retry_memory, facts).mode
            return updates
        updates["session_turns"] = memory["session_turns"] + 1
        for sealed_key, memory_key, identifiers in (
                ("frontier_exposure", "frontier_exposures", "implementations"),
                ("pending_proposal_exposure", "pending_proposal_exposures", "proposals"),
                ("trial_exposure", "trial_exposures", "proposals"),
                ("learning_exposure", "learning_exposures", "candidates")):
            delivery = turn.get(sealed_key)
            if delivery and delivery[identifiers]:
                exposures = dict(memory[memory_key])
                seen = dict(exposures.get(delivery["comparison_key"], {}))
                seen.update({identity: turn["number"] for identity in delivery[identifiers]})
                exposures[delivery["comparison_key"]] = seen
                updates[memory_key] = exposures
        reviews = turn.get("review_checkpoints", {})
        if "execution" in reviews:
            updates["execution_review_checkpoint"] = dict(reviews["execution"])
        if "strategy" in reviews:
            review = reviews["strategy"]
            updates["strategy_review_checkpoints"] = {
                **memory["strategy_review_checkpoints"], review["comparison_key"]: dict(review)}
        if "comparison" in reviews:
            updates["comparison_review_checkpoint"] = dict(reviews["comparison"])
            # Acknowledging the review changes the signal used by the preview.
            facts = outcome.evidence.signals(reviews["comparison"])
            updates["comparison_continuity"] = facts["comparison_continuity"]
        if "repeat" in reviews:
            review = reviews["repeat"]
            if review["signature"] in facts["measurement_signatures"]:
                updates["repeat_review_checkpoints"] = {
                    **memory["repeat_review_checkpoints"], review["comparison_key"]: review["signature"]}
        updates.update(failures=0, retry_at=None, last_error="", recovery_needed=False,
                       last_summary=receipt["summary"], next_action=receipt["next_action"],
                       last_agent_status=receipt["status"], next_mode="work")
        resolutions = [entry for entry in outcome.appended_events
                       if entry["event"] in {"measurement_decision", "measurement_stop"}]
        if resolutions:
            plans = facts["measurement_comparisons"]
            matched = [entry for entry in resolutions
                       if plans[entry["plan_id"]] == facts["objective_progress"]["comparison"]]
            if matched:
                updates["next_action"] = matched[-1]["next_action"]
        if receipt["status"] != "continue" or not updates["next_action"].strip():
            updates["next_mode"] = "rethink"
            updates["next_action"] = "Re-derive the remaining capability gap and execute a distinct feasible strategy"
        measurement_progress = (turn["mode"] == "measure" and
                                facts["comparison_continuity"]["distinct_observations"] >
                                (turn.get("context", {}).get("comparison_continuity") or {}).get("distinct_observations", 0))
        measurement_progress |= any(entry["event"] == "measurement_stop" for entry in outcome.appended_events)
        if turn["mode"] == "measure":
            measurement_progress |= any(entry["event"] in {"measurement_plan", "measurement_decision"} or
                                        entry["event"] == "candidate" and
                                        entry["result"].get("measurement_plan_id") and observed_implementation(entry)
                                        for entry in outcome.appended_events)
        if idle >= 2 and not measurement_progress:
            reviewed = turn["mode"] == "rethink" or (turn["mode"] == "repair" and turn.get("fresh_context"))
            updates["next_mode"] = "execute" if reviewed else "rethink"
            updates["retry_at"] = outcome.now + min(
                memory["retry_max_seconds"], memory["retry_base_seconds"] * max(1, idle - 1))
        refresh_requested = updates["next_mode"] == "rethink"
        preview = self._work({**memory, **updates}, facts)
        updates["next_mode"] = preview.mode
        if refresh_requested or preview.mode == "rethink":
            updates["session_id"] = None
        return updates
