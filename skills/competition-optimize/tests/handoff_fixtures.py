"""Wrap focused evidence fixtures in the actual handoff wire envelope."""
from campaign_handoff import bound_packet


def bounded_packet(packet, budget=48 * 1024):
    return bound_packet({"schema_version": 1, "archive_snapshot": {"size": 0, "sha256": "a" * 64},
                         "task_sha256": "t" * 64, "scope": "Focused accepted-evidence fixture", **packet},
                        budget=budget)
