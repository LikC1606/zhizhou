from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
resume = importlib.import_module("inspect_run_resume")


class RunResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = self.root / "task-contract.json"
        self.contract.write_text('{"budget": {"trials": 3}}\n', encoding="utf-8")
        self.ledger = self.root / "trials.jsonl"
        self.events = [{"event": "planned", "trial": "路线一", "hypothesis": "测试机制"},
                       {"event": "tool", "returncode": 0},
                       {"event": "completed", "trial": "路线一", "score": 0.5}]
        self.raw_lines = [(json.dumps(event, ensure_ascii=False) + "\r\n").encode("utf-8") for event in self.events]
        self.ledger.write_bytes(b"".join(self.raw_lines))

    def inspect(self, checkpoint: Path | None = None, max_events: int = 20) -> dict:
        return resume.inspect(self.contract, self.ledger, checkpoint, max_events)

    def save(self, report: dict, name: str = "checkpoint.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(report["checkpoint"]), encoding="utf-8")
        return path

    def test_paging_preserves_every_event_and_exact_utf8_byte_offsets(self) -> None:
        seen, checkpoint = [], None
        for index in range(3):
            report = self.inspect(checkpoint, 1)
            seen.extend(item["event"] for item in report["events"])
            expected = sum(map(len, self.raw_lines[:index + 1]))
            self.assertEqual(report["through_byte"], expected)
            self.assertEqual(report["checkpoint"]["ledger"]["sha256"], resume.digest(self.ledger.read_bytes()[:expected]))
            self.assertEqual(report["has_more"], index < 2)
            checkpoint = self.save(report, f"checkpoint-{index}.json")
        self.assertEqual(seen, self.events)
        self.assertEqual(self.inspect(checkpoint)["events"], [])

    def test_append_returns_only_new_events_without_budget_or_promotion_inference(self) -> None:
        checkpoint = self.save(self.inspect())
        new_event = {"event": "planned", "trial": "repair", "command": "do not execute this"}
        with self.ledger.open("ab") as stream:
            stream.write((json.dumps(new_event) + "\n").encode())
        report = self.inspect(checkpoint)
        self.assertEqual([item["event"] for item in report["events"]], [new_event])
        self.assertEqual(report["from_byte"], sum(map(len, self.raw_lines)))
        self.assertEqual(report["validity_scope"], "checkpoint_and_jsonl_syntax_only")
        self.assertIn("budget", report["unchecked"])
        self.assertIn("promotion", report["unchecked"])

    def test_empty_and_blank_lines_do_not_create_fake_events(self) -> None:
        self.ledger.write_bytes(b"")
        empty = self.inspect()
        self.assertEqual(empty["through_byte"], 0)
        self.assertEqual(empty["events"], [])
        checkpoint = self.save(empty)
        self.ledger.write_bytes(b"\r\n" + self.raw_lines[0] + b"\n\n")
        report = self.inspect(checkpoint, 1)
        self.assertEqual(report["emitted_events"], 1)
        self.assertEqual(report["through_byte"], len(self.ledger.read_bytes()))
        self.assertFalse(report["has_more"])

    def test_changed_contract_prefix_and_truncated_ledger_invalidate_checkpoint(self) -> None:
        checkpoint = self.save(self.inspect())
        original_contract, original_ledger = self.contract.read_bytes(), self.ledger.read_bytes()
        for kind, target, raw in [
            ("contract_changed", self.contract, original_contract + b"\n"),
            ("ledger_prefix_changed", self.ledger, original_ledger.replace(b"0.5", b"0.6")),
            ("ledger_truncated", self.ledger, self.raw_lines[0]),
        ]:
            with self.subTest(kind=kind):
                target.write_bytes(raw)
                with self.assertRaises(resume.ResumeFailure) as caught:
                    self.inspect(checkpoint)
                self.assertEqual(caught.exception.kind, kind)
                self.contract.write_bytes(original_contract)
                self.ledger.write_bytes(original_ledger)

    def test_partial_invalid_or_nonfinite_events_block_even_beyond_output_page(self) -> None:
        for raw in [b'{"event":"completed"}', b'{"event":\n', b'[]\n',
                    b'{"value":NaN}\n', b'{"value":1e400}\n', b'{"trial":1,"trial":2}\n', b'\xff\n']:
            with self.subTest(raw=raw):
                self.ledger.write_bytes(self.raw_lines[0] + raw)
                with self.assertRaises(resume.ResumeFailure):
                    self.inspect(max_events=1)

    def test_malformed_or_wrong_path_checkpoints_are_rejected(self) -> None:
        report = self.inspect(max_events=1)
        for mutate in [lambda c: c.update(schema_version=True),
                       lambda c: c["ledger"].update(bytes=True),
                       lambda c: c["ledger"].update(bytes=-1),
                       lambda c: c["ledger"].update(sha256="wrong"),
                       lambda c: c["contract"].update(path=str(self.ledger)),
                       lambda c: c.update(ledger=[]),
                       lambda c: c["ledger"].update(bytes=1, sha256=resume.digest(self.ledger.read_bytes()[:1]))]:
            checkpoint = json.loads(json.dumps(report["checkpoint"]))
            mutate(checkpoint)
            file = self.root / "malformed.json"
            file.write_text(json.dumps(checkpoint), encoding="utf-8")
            with self.subTest(checkpoint=checkpoint), self.assertRaises(resume.ResumeFailure):
                self.inspect(file)

    def test_invalid_source_or_page_size_is_not_accepted(self) -> None:
        for count in [0, 1001, True]:
            with self.subTest(count=count), self.assertRaises(resume.ResumeFailure):
                self.inspect(max_events=count)
        for contract in [b"[]", b'{"budget":1,"budget":2}', b'{"value":Infinity}']:
            self.contract.write_bytes(contract)
            with self.subTest(contract=contract), self.assertRaises(resume.ResumeFailure):
                self.inspect()

    def test_concurrent_append_is_deferred_and_prefix_rewrite_is_blocked(self) -> None:
        original_read = Path.read_bytes
        ledger_raw = self.ledger.read_bytes()
        appended = b'{"event":"later"}\n'
        for append in [True, False]:
            self.ledger.write_bytes(ledger_raw)
            calls = 0
            def change_after_read(path):
                nonlocal calls
                raw = original_read(path)
                if path == self.ledger:
                    calls += 1
                    if calls == 1:
                        path.write_bytes(ledger_raw + appended if append else ledger_raw.replace(b"0.5", b"0.6"))
                return raw
            with patch.object(Path, "read_bytes", change_after_read):
                if append:
                    report = self.inspect()
                    self.assertTrue(report["source_appended_during_inspection"])
                    self.assertTrue(report["has_more"])
                    self.assertEqual(report["through_byte"], len(ledger_raw))
                else:
                    with self.assertRaises(resume.ResumeFailure) as caught:
                        self.inspect()
                    self.assertEqual(caught.exception.kind, "ledger_changed")
            if append:
                checkpoint = self.save(report)
                self.assertEqual(self.inspect(checkpoint)["events"][0]["event"], {"event": "later"})

    def test_cli_never_overwrites_checkpoint_or_sources_and_fails_without_saving_partial_state(self) -> None:
        checkpoint = self.root / "中文检查点.json"
        command = [sys.executable, "-X", "utf8", str(SCRIPT_DIR / "inspect_run_resume.py"),
                   "--contract", str(self.contract), "--ledger", str(self.ledger),
                   "--save-checkpoint", str(checkpoint), "--max-events", "1"]
        original = {path: path.read_bytes() for path in [self.contract, self.ledger]}
        first = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(first.returncode, 0, first.stderr)
        checkpoint_raw = checkpoint.read_bytes()
        repeated = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(repeated.returncode, 2)
        self.assertEqual(checkpoint.read_bytes(), checkpoint_raw)
        self.assertTrue(all(path.read_bytes() == raw for path, raw in original.items()))
        new_checkpoint = self.root / "partial-checkpoint.json"
        self.ledger.write_bytes(self.ledger.read_bytes() + b'{"event":')
        partial_command = [str(new_checkpoint) if arg == str(checkpoint) else arg for arg in command]
        failed = subprocess.run(partial_command, capture_output=True, encoding="utf-8", timeout=15)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(json.loads(failed.stderr)["error"]["type"], "incomplete_event")
        self.assertFalse(new_checkpoint.exists())


if __name__ == "__main__":
    unittest.main()
