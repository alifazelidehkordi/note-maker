from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import batch_common
import diagnostics
from artifact_validation import ArtifactValidationError, ValidationResult


class FakeDriver:
    title = "ChatGPT"
    page_source = "<html><body>private page</body></html>"

    def __init__(self, *, screenshot_error: Exception | None = None) -> None:
        self.screenshot_error = screenshot_error

    def save_screenshot(self, path: str) -> bool:
        if self.screenshot_error is not None:
            raise self.screenshot_error
        Path(path).write_bytes(b"png")
        return True


class DiagnosticsTests(unittest.TestCase):
    def test_final_failure_writes_metadata_response_and_screenshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = diagnostics.save_failure_diagnostics(
                driver=FakeDriver(),
                output_dir=Path(tmp),
                run_id="run-1",
                job_key="source.pdf",
                attempt=3,
                max_attempts=3,
                stage="download",
                expected_extensions={".md"},
                source="inputs/source.pdf",
                prompt_hash="sha256:abc",
                error=RuntimeError("missing download"),
                response_text="assistant response",
                final=True,
            )

            self.assertEqual(
                result.directory,
                Path(tmp).resolve() / "diagnostics" / "run-1" / "source.pdf",
            )
            self.assertEqual(
                (result.directory / "last_response.txt").read_text(encoding="utf-8"),
                "assistant response",
            )
            self.assertEqual((result.directory / "last_state.png").read_bytes(), b"png")
            metadata = json.loads(
                (result.directory / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["stage"], "download")
            self.assertEqual(metadata["attempt"], 3)
            self.assertTrue(metadata["final_attempt"])
            self.assertEqual(metadata["expected_extensions"], [".md"])
            self.assertEqual(metadata["error_type"], "RuntimeError")
            self.assertEqual(result.capture_errors, ())

    def test_intermediate_attempt_uses_separate_attempt_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = diagnostics.save_failure_diagnostics(
                driver=FakeDriver(),
                output_dir=Path(tmp),
                run_id="run-2",
                job_key="section 01 Topic",
                attempt=1,
                max_attempts=3,
                stage="automation",
                expected_extensions={".opml"},
                source="section.md",
                prompt_hash="sha256:def",
                error=TimeoutError("timeout"),
                final=False,
            )
            self.assertEqual(result.directory.name, "attempt-01")
            self.assertEqual(result.directory.parent.name, "attempts")

    def test_screenshot_failure_does_not_block_metadata_or_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = diagnostics.save_failure_diagnostics(
                driver=FakeDriver(screenshot_error=RuntimeError("no display")),
                output_dir=Path(tmp),
                run_id="run-3",
                job_key="source.pdf",
                attempt=2,
                max_attempts=2,
                stage="automation",
                expected_extensions={".md"},
                source="source.pdf",
                prompt_hash="sha256:ghi",
                error=RuntimeError("browser failed"),
                response_text="last text",
            )
            self.assertTrue((result.directory / "metadata.json").exists())
            self.assertTrue((result.directory / "last_response.txt").exists())
            self.assertFalse((result.directory / "last_state.png").exists())
            self.assertTrue(any(item.startswith("screenshot:") for item in result.capture_errors))
            metadata = json.loads(
                (result.directory / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertTrue(any(item.startswith("screenshot:") for item in metadata["capture_errors"]))

    def test_page_source_is_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = dict(
                driver=FakeDriver(),
                output_dir=Path(tmp),
                job_key="source.pdf",
                attempt=1,
                max_attempts=1,
                stage="download",
                expected_extensions={".md"},
                source="source.pdf",
                prompt_hash="sha256:jkl",
                error=RuntimeError("failed"),
            )
            without = diagnostics.save_failure_diagnostics(run_id="run-no-html", **base)
            with_html = diagnostics.save_failure_diagnostics(
                run_id="run-html", save_page_source=True, **base
            )
            self.assertFalse((without.directory / "page_source.html").exists())
            self.assertEqual(
                (with_html.directory / "page_source.html").read_text(encoding="utf-8"),
                FakeDriver.page_source,
            )

    def test_rejected_candidate_is_copied_into_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejected = Path(tmp) / "rejected.md"
            rejected.write_text("invalid", encoding="utf-8")
            result = diagnostics.save_failure_diagnostics(
                driver=FakeDriver(),
                output_dir=Path(tmp),
                run_id="run-4",
                job_key="source.pdf",
                attempt=1,
                max_attempts=1,
                stage="validation",
                expected_extensions={".md"},
                source="source.pdf",
                prompt_hash="sha256:mno",
                error=RuntimeError("invalid"),
                validation_errors=("Missing H1",),
                rejected_path=rejected,
            )
            copied = result.directory / "downloaded_candidate.md"
            self.assertEqual(copied.read_text(encoding="utf-8"), "invalid")

    def test_retry_saves_only_final_failure_by_default(self):
        callbacks: list[tuple[int, bool, str]] = []

        def callback(_driver, attempt, _limit, error, final):
            callbacks.append((attempt, final, type(error).__name__))

        with mock.patch.object(batch_common, "driver_is_alive", return_value=True), mock.patch.object(
            batch_common, "reset_chat"
        ), mock.patch.object(batch_common.time, "sleep"):
            ok, _ = batch_common.run_with_retries(
                "job",
                FakeDriver(),
                None,
                lambda _driver: False,
                max_attempts=3,
                diagnostic_callback=callback,
            )

        self.assertFalse(ok)
        self.assertEqual(callbacks, [(3, True, "NoValidArtifactError")])

    def test_retry_saves_all_failed_attempts_when_requested(self):
        callbacks: list[tuple[int, bool]] = []

        def callback(_driver, attempt, _limit, _error, final):
            callbacks.append((attempt, final))

        with mock.patch.object(batch_common, "driver_is_alive", return_value=True), mock.patch.object(
            batch_common, "reset_chat"
        ), mock.patch.object(batch_common.time, "sleep"):
            ok, _ = batch_common.run_with_retries(
                "job",
                FakeDriver(),
                None,
                lambda _driver: False,
                max_attempts=3,
                diagnostic_callback=callback,
                save_all_diagnostics=True,
            )

        self.assertFalse(ok)
        self.assertEqual(callbacks, [(1, False), (2, False), (3, True)])

    def test_diagnostic_callback_failure_does_not_mask_retry_result(self):
        def broken_callback(*_args):
            raise OSError("disk full")

        with mock.patch.object(batch_common, "driver_is_alive", return_value=True), mock.patch.object(
            batch_common, "reset_chat"
        ), mock.patch.object(batch_common.time, "sleep"), mock.patch.object(
            batch_common, "batch_log"
        ) as log:
            ok, _ = batch_common.run_with_retries(
                "job",
                FakeDriver(),
                None,
                lambda _driver: False,
                max_attempts=1,
                diagnostic_callback=broken_callback,
            )

        self.assertFalse(ok)
        self.assertTrue(any("could not save diagnostics" in call.args[0] for call in log.call_args_list))

    def test_capture_retry_failure_records_validation_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejected = Path(tmp) / "invalid.md"
            rejected.write_text("bad", encoding="utf-8")
            error = ArtifactValidationError(
                Path(tmp) / "output.md",
                ValidationResult(False, ("Missing H1", "Missing H2"), "markdown"),
                rejected_path=rejected,
            )
            with mock.patch.object(
                batch_common.core, "latest_assistant_text", return_value="assistant"
            ):
                result = batch_common.capture_retry_failure(
                    driver=FakeDriver(),
                    output_dir=Path(tmp),
                    run_id="run-validation",
                    job_key="source.pdf",
                    attempt=2,
                    max_attempts=2,
                    expected_extensions={".md"},
                    source="source.pdf",
                    prompt_hash="sha256:pqr",
                    error=error,
                    final=True,
                )
            metadata = json.loads(
                (result.directory / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["stage"], "validation")
            self.assertEqual(metadata["validation_errors"], ["Missing H1", "Missing H2"])
            self.assertTrue((result.directory / "downloaded_candidate.md").exists())


if __name__ == "__main__":
    unittest.main()
