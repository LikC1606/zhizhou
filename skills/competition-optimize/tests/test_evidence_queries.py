from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import test_optimization_brief as fixtures
from evidence_queries import BriefQuery, EvidenceSnapshot
from candidate_evidence import ArchiveFailure
import candidate_archive as archive


class EvidenceSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.OptimizationBriefTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def snapshot(self, *, observed_only: bool = False) -> EvidenceSnapshot:
        return EvidenceSnapshot(self.fixture.path, archive.read_records(self.fixture.path), observed_only=observed_only)

    def test_multiple_queries_keep_complete_comparison_and_exact_trace(self) -> None:
        f = self.fixture
        f.record("control", 10, status="incumbent")
        f.propose("complete", "control", route="current")
        f.record("improved", 11, parent="control", proposal="complete", feedback="Measured improvement")
        f.record("other-contract", 100, comparison={"workload_hash": "foreign"})
        records = archive.read_records(f.path)
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("snapshot construction performs no evidence I/O")):
            snapshot = EvidenceSnapshot(f.path, records)
        self.assertEqual(snapshot.brief(BriefQuery(anchor="control"))["best_development"], "improved")
        self.assertEqual(snapshot.brief(BriefQuery(anchor="other-contract"))["best_development"], "other-contract")
        trace = snapshot.trace(proposal_id="complete")
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["candidate_id"], "improved")
        self.assertEqual(trace[0]["objective_gain_vs_parents"], {"control": 1.0})
        trials = snapshot.trials(f.records["control"]["comparison"], set())
        self.assertEqual([trial["proposal_id"] for trial in trials["selection"]], ["complete"])
        with self.assertRaises(ArchiveFailure) as error:
            snapshot.trace(proposal_id="missing")
        self.assertEqual(error.exception.kind, "unknown_proposal")

    def test_observed_policy_does_not_upgrade_manual_score_claims(self) -> None:
        f = self.fixture
        f.record("executed", 10)
        # The fixture's explicit flags preserve a comparable contract while the
        # missing result cannot supply actual adapter execution provenance.
        f.record("manual", 99, result=False)
        # Match the manually specified fixture contract to the executed result.
        records = archive.read_records(f.path)
        records[-1]["comparison"] = dict(records[0]["comparison"])
        legacy = EvidenceSnapshot(f.path, records).brief()
        measured = EvidenceSnapshot(f.path, records, observed_only=True).brief()
        self.assertEqual(legacy["best_development"], "manual")
        self.assertEqual(measured["best_development"], "executed")
        self.assertEqual(measured["candidates"]["manual"]["identity_checks"]["result_bytes"], "not_recorded")

    def test_queries_recheck_selected_bytes_and_do_not_write_archive(self) -> None:
        f = self.fixture
        f.record("control", 10)
        before = f.path.read_bytes()
        snapshot = self.snapshot()
        self.assertEqual(snapshot.brief()["best_development"], "control")
        result = Path(f.records["control"]["result"]["result_path"])
        result.write_bytes(result.read_bytes() + b" ")
        with self.assertRaises(ArchiveFailure) as error:
            snapshot.brief()
        self.assertEqual(error.exception.kind, "result_changed")
        self.assertEqual(f.path.read_bytes(), before)

    def test_query_module_and_trial_reader_do_not_import_archive_cli(self) -> None:
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        program = ("import sys; sys.path.insert(0, sys.argv[1]); "
                   "from evidence_queries import EvidenceSnapshot; "
                   "from campaign_trials import delivered_trials; "
                   "assert EvidenceSnapshot(None, []).trace() == []; "
                   "assert delivered_trials({}) == []; "
                   "assert 'candidate_archive' not in sys.modules; "
                   "assert 'campaign_search' not in sys.modules")
        result = subprocess.run([sys.executable, "-B", "-c", program, str(scripts)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
