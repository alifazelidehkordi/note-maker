from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import batch_common
import batch_pdf
import diagnostics
from artifact_validation import ArtifactValidationError
from browser_runtime import BrowserCrashedError, BrowserResponseTimeout, RateLimitError
from parallel_runtime.resilience import RetryBudgetPolicy
from tests.fakes.fake_browser_provider import (
    FakeBrowserPlan,
    FakeBrowserProvider,
    FakeBrowserSession,
)

VALID_MARKDOWN = """# Generated Note

## Explanation

This deterministic generated note contains enough useful content to pass the Markdown artifact validator during provider contract tests.
"""


class FakeBrowserProviderTests(unittest.TestCase):
    def test_pdf_process_succeeds_using_only_browser_session_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            candidate = root / "candidate.md"
            candidate.write_text(VALID_MARKDOWN, encoding="utf-8")
            output_dir = root / "output"
            session = FakeBrowserSession(FakeBrowserPlan(download_path=candidate))

            with mock.patch.object(batch_pdf.time, "time_ns", return_value=123):
                self.assertTrue(
                    batch_pdf.process_one(
                        session,
                        "create notes",
                        source,
                        output_dir,
                        None,
                        download_timeout=19,
                        save_diagnostics=False,
                        output_ext="md",
                    )
                )

            self.assertTrue((output_dir / "source.md").exists())
            names = [item.operation for item in session.operations]
            self.assertEqual(
                names,
                [
                    "start_new_chat",
                    "select_model",
                    "snapshot_downloads",
                    "upload",
                    "assistant_message_count",
                    "send_message",
                    "wait_for_response",
                    "resolve_download",
                ],
            )
            resolve = session.operations[-1].payload
            self.assertEqual(resolve["expected_extensions"], [".md"])
            self.assertEqual(resolve["timeout"], 19)

    def test_timeout_and_crash_are_deterministic_typed_failures(self):
        timeout_session = FakeBrowserSession(FakeBrowserPlan.timeout())
        with self.assertRaises(BrowserResponseTimeout):
            from browser_runtime import ResponseWaitRequest

            timeout_session.wait_for_response(ResponseWaitRequest())

        crash_session = FakeBrowserSession(FakeBrowserPlan.crash())
        with self.assertRaises(BrowserCrashedError):
            crash_session.send_message("prompt")

    def test_invalid_download_is_rejected_by_existing_artifact_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"pdf")
            invalid = root / "candidate.md"
            invalid.write_text("not a valid note", encoding="utf-8")
            session = FakeBrowserSession(FakeBrowserPlan(download_path=invalid))
            with self.assertRaises(ArtifactValidationError):
                batch_pdf.process_one(
                    session,
                    "create notes",
                    source,
                    root / "output",
                    None,
                    download_timeout=5,
                    save_diagnostics=False,
                    output_ext="md",
                )

    def test_diagnostics_use_provider_methods_not_driver_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = FakeBrowserSession()
            result = diagnostics.save_failure_diagnostics(
                driver=session,
                output_dir=Path(tmp),
                run_id="provider-diagnostics",
                job_key="job",
                attempt=1,
                max_attempts=1,
                stage="automation",
                expected_extensions={".md"},
                source="source.pdf",
                prompt_hash="sha256:test",
                error=RuntimeError("failed"),
                response_text="response",
                save_page_source=True,
            )
            self.assertEqual((result.directory / "last_state.png").read_bytes(), b"fake-png")
            self.assertEqual(
                (result.directory / "page_source.html").read_text(encoding="utf-8"),
                "<html><body>fake browser</body></html>",
            )

    def test_retry_orchestrator_honors_provider_rate_limit_cooldown(self):
        session = FakeBrowserSession()
        attempts = iter([RateLimitError("slow down", retry_after=17), True])

        def process_once(_session):
            result = next(attempts)
            if isinstance(result, BaseException):
                raise result
            return result

        with mock.patch.object(batch_common.time, "sleep") as sleep:
            succeeded, returned = batch_common.run_with_retries(
                "rate-limited-job",
                session,
                None,
                process_once,
                max_attempts=2,
                retry_delay=5,
            )

        self.assertTrue(succeeded)
        self.assertIs(returned, session)
        sleep.assert_called_once_with(17)

    def test_rate_limit_retry_does_not_refresh_or_reset_chat(self):
        session = FakeBrowserSession()
        attempts = iter([RateLimitError("slow down", retry_after=17), True])
        policy = RetryBudgetPolicy(
            content_attempts=1,
            network_retries=0,
            browser_retries=0,
            download_retries=0,
            rate_limit_retries=1,
            jitter_ratio=0,
        )

        def process_once(_session):
            result = next(attempts)
            if isinstance(result, BaseException):
                raise result
            return result

        with (
            mock.patch.object(batch_common, "reset_chat") as reset_chat,
            mock.patch.object(batch_common.time, "sleep") as sleep,
        ):
            succeeded, returned = batch_common.run_with_retries(
                "rate-limited-job",
                session,
                None,
                process_once,
                retry_policy=policy,
            )

        self.assertTrue(succeeded)
        self.assertIs(returned, session)
        reset_chat.assert_not_called()
        sleep.assert_called_once_with(17)

    def test_rate_limit_waiter_repeatedly_dismisses_without_navigation(self):
        class WatchableSession:
            def __init__(self):
                self.dismissals = 0

            def dismiss_rate_limit_modal(self):
                self.dismissals += 1
                return True

        session = WatchableSession()
        sleeps = []
        batch_common._wait_retry_delay(
            session,
            5,
            sleep_fn=sleeps.append,
            modal_poll_interval=2,
        )
        self.assertEqual(session.dismissals, 3)
        self.assertEqual(sleeps, [2, 2, 1])

    def test_fake_provider_records_launch_configuration(self):
        provider = FakeBrowserProvider()
        session = provider.open_session()
        self.assertIs(session, provider.sessions[0])
        self.assertEqual(provider.open_options[0].browser, "chrome")


if __name__ == "__main__":
    unittest.main()
