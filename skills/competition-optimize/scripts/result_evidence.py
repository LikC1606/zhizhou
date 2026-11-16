"""Decode legacy adapter results and resolve their observation contract.

This module knows result field aliases and claim precedence, but never reads or
writes a candidate archive. Manual claims remain claims: a resolved score does
not create result provenance, an executed snapshot or a promotion decision.
"""
from __future__ import annotations

import math
import pathlib
from dataclasses import dataclass
from typing import Any

import candidate_profiles
import resource_profiles
from candidate_evidence import ArchiveFailure, DEVELOPMENT_ROLES, DIRECTIONS, KINDS, load_json, sha256


def finite_number(value: Any, field: str) -> float:
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))
    except OverflowError:
        valid = False
    if not valid:
        raise ArchiveFailure("invalid_candidate", f"{field} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class ObservationClaims:
    objective_value: float | None = None
    objective_direction: str | None = None
    objective_kind: str | None = None
    objective_name: str | None = None
    evaluator_hash: str | None = None
    workload_hash: str | None = None
    score_model_hash: str | None = None
    stage: str | None = None
    valid: bool | None = None
    role: str | None = None


@dataclass(frozen=True)
class ResolvedObservation:
    objective: dict[str, Any]
    comparison: dict[str, Any]
    valid: bool
    role: str

    @property
    def purpose(self) -> str:
        """Use the resolved evidence role, never infer purpose from fidelity."""
        return "confirmation" if self.role == "confirmation" else "development"

    @property
    def fidelity(self) -> str | None:
        """Known legacy algorithm fidelities; custom protocol stages stay opaque."""
        stage = self.comparison.get("stage")
        return stage if stage in {"smoke", "short", "full"} else None

    @property
    def operation(self) -> str:
        stage = self.comparison.get("stage")
        return stage if stage in {"package", "rules"} else "evaluate"


@dataclass(frozen=True)
class ResultEvidence:
    metadata: dict[str, Any]

    @property
    def source_kind(self) -> str:
        return "adapter_result" if self.metadata.get("result_path") else "manual_claim"

    @classmethod
    def read(cls, path: pathlib.Path | None, *, include_case_profile: bool = True,
             include_resource_profile: bool = True) -> "ResultEvidence":
        """Read one adapter result, preserving legacy field mappings and hashes."""
        if path is None:
            return cls({})
        path = path.expanduser().resolve(strict=True)
        raw = path.read_bytes()
        value = load_json(raw, str(path))
        if not isinstance(value, dict):
            raise ArchiveFailure("invalid_result", "Result must be a JSON object")
        metadata: dict[str, Any] = {"result_path": str(path), "result_sha256": sha256(raw),
                                   "execution_status": value.get("status"),
                                   "validity_scope": value.get("validity_scope", "adapter_declared_checks"),
                                   "unchecked_rules": value.get("unchecked_rules", ["training_and_hard_rule_provenance"])}
        for key in ("candidate_hash", "candidate_scope", "evaluator_hash", "workload_hash", "score_model_hash", "stage"):
            if key in value:
                metadata[key] = value[key]
        if isinstance(value.get("evaluation"), dict):
            for key in ("config_hash", "split_hash", "stage", "runtime_environment"):
                if key in value["evaluation"]:
                    metadata[key] = value["evaluation"][key]
            evaluation = value["evaluation"]
            if "measurement_plan_id" in evaluation:
                for key in ("measurement_plan_id", "measurement_run_id", "seeds", "repetitions"):
                    if key in evaluation:
                        metadata[key] = evaluation[key]
            expected, completed = evaluation.get("expected_cases"), evaluation.get("completed_cases")
            if expected is not None and (type(expected) is not int or expected <= 0 or expected != completed):
                metadata["partial"] = True
        if isinstance(value.get("metrics"), dict) and value["metrics"].get("partial"):
            metadata["partial"] = True
        if "runtime_environment" in value:
            metadata["runtime_environment"] = value["runtime_environment"]
        if "valid" in value:
            metadata["valid"] = value["valid"]
        elif "correct" in value:
            metadata["valid"] = value["correct"]
        if metadata.get("valid") is not None and type(metadata["valid"]) is not bool:
            raise ArchiveFailure("invalid_result", "Result validity must be boolean or null")
        if value.get("status") != "success" or metadata.get("partial"):
            metadata["valid"] = False
        score = value.get("score")
        if isinstance(score, dict):
            if score.get("kind") is not None and score["kind"] not in KINDS:
                raise ArchiveFailure("invalid_result", "Unknown score kind")
            if score.get("direction") is not None and score["direction"] not in DIRECTIONS:
                raise ArchiveFailure("invalid_result", "Unknown score direction")
            metadata["objective_kind"] = score.get("kind", "unknown")
            metadata["objective_name"] = score.get("metric", score.get("aggregation"))
            metadata["components"] = score.get("components", {})
            if score.get("direction") in DIRECTIONS:
                metadata["objective_direction"] = score["direction"]
            if score.get("value") is not None:
                metadata["objective_value"] = finite_number(score["value"], "result.score.value")
        if isinstance(value.get("metrics"), dict):
            metadata["metric_summary"] = value["metrics"].get("summary", {})
        if value.get("elapsed_seconds") is not None:
            metadata["elapsed_seconds"] = finite_number(value["elapsed_seconds"], "result.elapsed_seconds")
        if include_case_profile and "case_profile" in value:
            try:
                metadata["case_profile"] = candidate_profiles.describe(value["case_profile"])
            except candidate_profiles.ProfileFailure as exc:
                raise ArchiveFailure("invalid_case_profile", str(exc)) from exc
        if include_resource_profile and "resource_profile" in value:
            try:
                metadata["resource_profile"] = resource_profiles.describe(value["resource_profile"])
            except resource_profiles.ResourceFailure as exc:
                raise ArchiveFailure("invalid_resource_profile", str(exc)) from exc
        return cls(metadata)

    def resolve(self, claims: ObservationClaims, *, candidate_status: str | None = None) -> ResolvedObservation:
        """Resolve declared values without upgrading them to executed evidence.

        Adapter values take precedence: conflicting explicit claims fail. The
        archive still decides snapshot/execution eligibility from the result
        provenance plus code/recipe evidence, not from these resolved values.
        """
        result = self.metadata
        objective: dict[str, Any] = {}
        direction = claims.objective_direction or result.get("objective_direction")
        value = claims.objective_value
        if value is None and result.get("objective_value") is not None:
            value = result["objective_value"]
        if value is not None:
            objective["value"] = finite_number(value, "objective_value")
        if direction is not None:
            if direction not in DIRECTIONS:
                raise ArchiveFailure("invalid_candidate", "objective_direction must be maximize or minimize")
            objective["direction"] = direction
        if value is not None and direction is None:
            raise ArchiveFailure("invalid_candidate", "A scalar objective value requires an explicit direction")
        objective["kind"] = claims.objective_kind or result.get("objective_kind", "unknown")
        objective["name"] = claims.objective_name or result.get("objective_name")
        objective["components"] = result.get("components", {})
        for flag_value, key in [(claims.objective_value, "objective_value"),
                                (claims.objective_direction, "objective_direction"),
                                (claims.objective_kind, "objective_kind"), (claims.objective_name, "objective_name"),
                                (claims.evaluator_hash, "evaluator_hash"), (claims.stage, "stage"),
                                (claims.workload_hash, "workload_hash" if "workload_hash" in result else "split_hash"),
                                (claims.score_model_hash, "score_model_hash")]:
            if flag_value is not None and result.get(key) is not None and flag_value != result[key]:
                raise ArchiveFailure("result_override", f"Explicit {key} contradicts the evaluator result")
        validity = claims.valid
        if validity is None and "valid" in result:
            validity = result["valid"]
        if validity is None:
            raise ArchiveFailure("invalid_candidate", "Provide --valid/--invalid or a result with valid/correct")
        if validity and result.get("valid") is False:
            raise ArchiveFailure("result_override", "Cannot declare a failed/partial/invalid result valid")
        if candidate_status in {"incumbent", "runner_up"} and not validity:
            raise ArchiveFailure("invalid_candidate", "Invalid candidates cannot be an incumbent or runner-up")
        role = claims.role or ("confirmation" if result.get("stage") in {"confirmation", "test", "holdout"} else "development")
        if role in DEVELOPMENT_ROLES and (claims.stage or result.get("stage")) in {"confirmation", "test", "holdout"}:
            raise ArchiveFailure("result_override", "Confirmation/test evidence cannot become development or diagnostic through a flag")
        comparison = {
            "evaluator_hash": claims.evaluator_hash or result.get("evaluator_hash"),
            "workload_hash": claims.workload_hash or result.get("workload_hash") or result.get("split_hash"),
            "score_model_hash": claims.score_model_hash or result.get("score_model_hash"),
            "config_hash": result.get("config_hash"), "stage": claims.stage or result.get("stage"),
            "runtime_environment": result.get("runtime_environment"),
            "objective_kind": objective["kind"], "objective_name": objective["name"],
            "direction": direction,
        }
        return ResolvedObservation(objective, comparison, bool(validity), role)
