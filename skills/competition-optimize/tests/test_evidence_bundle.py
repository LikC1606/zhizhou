from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_optimization_brief as basic_fixtures
import test_implementation_reviews as review_fixtures
import test_scoped_learning as learning_fixtures
import candidate_archive as archive
from candidate_evidence import ArchiveFailure
from evidence_bundle import export_bundle, verify_bundle
from evidence_files import ArtifactResolver
from evidence_queries import BriefQuery, EvidenceSnapshot


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class EvidenceBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "bundle"
        self.fixture = self.make_fixture(basic_fixtures.OptimizationBriefTests)

    def make_fixture(self, fixture_type):
        fixture = fixture_type()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    @staticmethod
    def artifacts(entries: dict) -> list[Path]:
        return list(dict.fromkeys(Path(value) for entry in entries.values()
                                  for value in (*entry["artifact_paths"].values(), entry["result"]["result_path"])))

    @staticmethod
    def snapshot(bundle: Path) -> EvidenceSnapshot:
        resolver = ArtifactResolver(bundle)
        records = archive.parse_records(resolver.archive_path.read_bytes(), str(resolver.archive_original_path))
        return EvidenceSnapshot(resolver.archive_original_path, records, resolver=resolver)

    def assert_kind(self, kind: str, operation) -> None:
        with self.assertRaises(ArchiveFailure) as caught:
            operation()
        self.assertEqual(caught.exception.kind, kind)

    def test_move_preserves_raw_archive_queries_review_and_learning_seals(self) -> None:
        f = self.make_fixture(learning_fixtures.ScopedLearningTests)
        f.propose("learn")
        args, _ = f.arguments("child", 110, proposal="learn", learning=f.lesson(evidence=["control"]))
        review = {"fidelity": "yes", "actual_mechanism": "Explicit measured construction",
                  "missing_components": [], "code_evidence": [{"path": str(args.source), "detail": "Construction entry"}]}
        args.implementation_review = args.source.parent / "review.json"
        args.implementation_review.write_text(json.dumps(review), encoding="utf-8")
        child = archive.record_candidate(args)
        f.entries["child"] = child
        f.propose("apply", learning_from=["child"])
        f.record("application", 115, proposal="apply")
        raw = f.path.read_bytes()
        records = archive.read_records(f.path)
        before = EvidenceSnapshot(f.path, records)
        query = BriefQuery(learning_seen={})
        expected = (before.brief(query), before.trace(), before.trials(f.control["comparison"], set()))
        export_bundle(f.path, self.bundle, self.artifacts(f.entries))
        self.assertEqual(f.path.read_bytes(), raw)
        moved = self.root / "moved"
        self.bundle.rename(moved)
        shutil.rmtree(f.root)
        # The old machine/path may be reused after export. Resolving that path
        # again must not change the archive identity sealed into retrievals.
        f.root.mkdir()
        unrelated = self.root / "unrelated.jsonl"
        unrelated.write_bytes(b"")
        f.path.symlink_to(unrelated)
        resolver = ArtifactResolver(moved)
        self.assertEqual(resolver.archive_path.read_bytes(), raw)
        restored_records = archive.parse_records(resolver.archive_path.read_bytes(), str(resolver.archive_original_path))
        self.assertEqual(restored_records, records)
        restored = EvidenceSnapshot(resolver.archive_original_path, restored_records, resolver=resolver)
        actual = (restored.brief(query), restored.trace(), restored.trials(f.control["comparison"], set()))
        self.assertEqual(actual, expected)
        self.assertEqual(actual[1][0]["evidence"]["implementation_review"], child["implementation_review"])
        self.assertEqual(actual[1][0]["evidence"]["learning"]["evidence_sha256"], child["learning"]["evidence_sha256"])
        self.assertEqual(resolver.archive_path.read_bytes(), raw)

    def test_exported_directories_resolve_nested_proposal_and_review_paths(self) -> None:
        f = self.make_fixture(review_fixtures.ImplementationReviewTests)
        parent = f.record("recipe-parent", 101, scope="training_pipeline", recipe=True)
        f.propose("recipe-change", parent="recipe-parent")
        child = f.record("recipe-child", 102, proposal="recipe-change", scope="training_pipeline", recipe=True,
                         review=f.review())
        before = EvidenceSnapshot(f.path, archive.read_records(f.path))
        expected = (before.brief(), before.trace(), before.trials(parent["comparison"], set()))
        roots = list(dict.fromkeys(Path(entry["artifact_paths"]["source"]).parent for entry in f.entries.values()))
        export_bundle(f.path, self.bundle, roots)
        shutil.rmtree(f.root)
        restored = self.snapshot(self.bundle)
        self.assertEqual((restored.brief(), restored.trace(), restored.trials(parent["comparison"], set())), expected)
        self.assertEqual(restored.trace()[0]["code_targets"][0]["path"], parent["artifact_paths"]["configuration"] + "/train.py")
        self.assertEqual(restored.trace()[0]["evidence"]["implementation_review"], child["implementation_review"])

    def test_partial_export_never_falls_back_to_existing_original_files(self) -> None:
        entry = self.fixture.record("control", 10)
        result = Path(entry["result"]["result_path"])
        export_bundle(self.fixture.path, self.bundle, [result])
        self.assertTrue(Path(entry["artifact_paths"]["source"]).exists())
        self.assertEqual(verify_bundle(self.bundle)["status"], "verified")
        self.assert_kind("unmapped_artifact", self.snapshot(self.bundle).brief)

    def test_tampered_bytes_fail_verification_and_existing_query_view(self) -> None:
        entry = self.fixture.record("control", 10)
        export_bundle(self.fixture.path, self.bundle, self.artifacts(self.fixture.records))
        resolver = ArtifactResolver(self.bundle)
        view = self.snapshot(self.bundle)
        self.assertEqual(view.brief()["best_development"], "control")
        for original, failure in ((entry["artifact_paths"]["source"], "parent_artifact_changed"),
                                  (entry["result"]["result_path"], "result_changed")):
            target = resolver.resolve_path(Path(original))
            raw = target.read_bytes()
            with self.subTest(original=original):
                target.write_bytes(raw + b" ")
                self.assert_kind("bundle_artifact_changed", lambda: verify_bundle(self.bundle))
                self.assert_kind(failure, view.brief)
                target.write_bytes(raw)
        resolver.archive_path.write_bytes(resolver.archive_path.read_bytes() + b"\n")
        self.assert_kind("bundle_artifact_changed", lambda: verify_bundle(self.bundle))

    def test_manifest_rejects_escaping_or_ambiguous_paths(self) -> None:
        self.fixture.record("control", 10)
        export_bundle(self.fixture.path, self.bundle, self.artifacts(self.fixture.records))
        manifest_path = self.bundle / "manifest.json"
        original = json.loads(manifest_path.read_bytes())
        variants = []
        for stored in ("../elsewhere", str(self.fixture.path)):
            changed = copy.deepcopy(original)
            changed["archive"]["stored_path"] = stored
            variants.append(changed)
        changed = copy.deepcopy(original)
        changed["archive"]["original_path"] = "relative/archive.jsonl"
        variants.append(changed)
        changed = copy.deepcopy(original)
        changed["artifacts"].append(changed["artifacts"][0])
        variants.append(changed)
        changed = copy.deepcopy(original)
        changed["artifacts"][0]["kind"] = []
        variants.append(changed)
        for changed in variants:
            with self.subTest(manifest=changed):
                manifest_path.write_text(json.dumps(changed), encoding="utf-8")
                self.assert_kind("invalid_bundle", lambda: ArtifactResolver(self.bundle))

    def test_bundle_does_not_follow_external_symlink_after_loading(self) -> None:
        entry = self.fixture.record("control", 10)
        export_bundle(self.fixture.path, self.bundle, self.artifacts(self.fixture.records))
        resolver = ArtifactResolver(self.bundle)
        source = Path(entry["artifact_paths"]["source"])
        target = resolver.resolve_path(source)
        # Identical outside bytes still cannot become an implicit export.
        target.unlink()
        target.symlink_to(source)
        self.assert_kind("invalid_bundle", lambda: resolver.resolve_path(source))
        self.assert_kind("invalid_bundle", lambda: ArtifactResolver(self.bundle))

    def test_directory_members_cannot_resolve_outside_explicit_export(self) -> None:
        entry = self.fixture.record("control", 10)
        source = Path(entry["artifact_paths"]["source"])
        export_bundle(self.fixture.path, self.bundle, [source.parent])
        resolver = ArtifactResolver(self.bundle)
        target = resolver.resolve_path(source)
        target.unlink()
        target.symlink_to(source)
        self.assert_kind("invalid_bundle", lambda: resolver.resolve_path(source))
        self.assert_kind("invalid_bundle", lambda: ArtifactResolver(self.bundle))

    def test_export_rejects_output_inside_selected_tree(self) -> None:
        entry = self.fixture.record("control", 10)
        source = Path(entry["artifact_paths"]["source"])
        nested = source.parent / "bundle"
        before = self.fixture.path.read_bytes()
        self.assert_kind("invalid_bundle", lambda: export_bundle(self.fixture.path, nested, [source.parent]))
        self.assertFalse(nested.exists())
        self.assertEqual(self.fixture.path.read_bytes(), before)

    def test_cli_export_verify_and_overwrite_refusal(self) -> None:
        self.fixture.record("control", 10)
        command = [sys.executable, "-B", str(SCRIPTS / "evidence_bundle.py")]
        export = [*command, "export", "--archive", str(self.fixture.path), "--output", str(self.bundle)]
        for path in self.artifacts(self.fixture.records):
            export += ["--artifact", str(path)]
        created = subprocess.run(export, capture_output=True, text=True, timeout=15)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(json.loads(created.stdout)["status"], "verified")
        manifest = (self.bundle / "manifest.json").read_bytes()
        verified = subprocess.run([*command, "verify", "--bundle", str(self.bundle / "manifest.json")],
                                  capture_output=True, text=True, timeout=15)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["archive"]["original_path"], str(self.fixture.path))
        duplicate = subprocess.run(export, capture_output=True, text=True, timeout=15)
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual(json.loads(duplicate.stderr)["error"]["type"], "output_exists")
        self.assertEqual((self.bundle / "manifest.json").read_bytes(), manifest)


if __name__ == "__main__":
    unittest.main()
