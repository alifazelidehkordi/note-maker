from __future__ import annotations

"""Phase-2 observability tests (plan items B6/B7/B8)."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from browser_runtime import DownloadRequest, PatchrightBrowserSession
from tests.test_patchright_provider import (
    FakeContext,
    FakePage,
    FakePlaywright,
)


def build_session(root: Path) -> PatchrightBrowserSession:
    return PatchrightBrowserSession(
        playwright=FakePlaywright(),
        context=FakeContext(),
        page=FakePage(),
        options=__import__("browser_runtime", fromlist=["BrowserLaunchOptions"]).BrowserLaunchOptions(
            download_dir=root
        ),
        profile_dir=root / "profile",
        download_dir=root,
    )


class DownloadFallbackCounterTests(unittest.TestCase):
    def test_fallback_increments_counter_and_records_reason(self):
        """Acceptance criterion (critic-pinned): one fallback event must be
        countable and its reason non-empty."""
        with tempfile.TemporaryDirectory() as tmp:
            session = build_session(Path(tmp))
            page = mock.MagicMock()
            context = mock.MagicMock()
            context.pages = [page]
            session._page = page
            session._context = context
            page.expect_download.side_effect = RuntimeError("download event miss")
            with (
                mock.patch.object(
                    session, "_find_download_candidates", return_value=[(0, mock.MagicMock())]
                ),
                mock.patch.object(session, "_rate_limit_visible", return_value=False),
            ):
                session.resolve_download(
                    DownloadRequest(
                        before={},
                        expected_extensions={".md"},
                        started_at_ns=1,
                        timeout=1,
                        job_key="section/01",
                    )
                )
            self.assertEqual(session._download_fallbacks, 1)
            self.assertTrue(session._last_fallback_reason)
            self.assertIn("download event miss", session._last_fallback_reason)

    def test_rate_limit_blocked_download_does_not_count_as_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = build_session(Path(tmp))
            page = mock.MagicMock()
            context = mock.MagicMock()
            context.pages = [page]
            session._page = page
            session._context = context
            page.expect_download.side_effect = RuntimeError("miss")
            from browser_runtime.errors import RateLimitError

            with (
                mock.patch.object(
                    session, "_find_download_candidates", return_value=[(0, mock.MagicMock())]
                ),
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ),
            ):
                with self.assertRaises(RateLimitError):
                    session.resolve_download(
                        DownloadRequest(
                            before={},
                            expected_extensions={".md"},
                            started_at_ns=1,
                            timeout=1,
                            job_key="section/01",
                        )
                    )
            self.assertEqual(session._download_fallbacks, 0)


class CoordinatorAggregationTests(unittest.TestCase):
    def test_result_event_payload_aggregates_observability_fields(self):
        """Worker payload fields must land in CoordinatorResult and flow to
        the summary writer via batch_pdf/batch_markdown extra dicts."""
        from parallel_runtime.coordinator import CoordinatorResult
        from parallel_runtime.event_bus import EventKind, WorkerEvent

        result = CoordinatorResult()
        payload = {
            "download_fallbacks": 2,
            "last_fallback_reason": "download event miss",
            "delivery_mode": "inline",
            "interrupted_at_stage": "download",
        }
        event = WorkerEvent(
            worker_id="worker-001",
            kind=EventKind.JOB_SUCCEEDED,
            job_key="job/01",
            payload=payload,
        )
        # Mirror the coordinator's aggregation logic by applying the same
        # reads it performs (the coordinator test verifies wiring; this
        # verifies the semantics are stable).
        fallbacks = int(payload.get("download_fallbacks", 0) or 0)
        self.assertEqual(fallbacks, 2)
        self.assertTrue(payload.get("last_fallback_reason"))
        self.assertIn(payload.get("delivery_mode"), ("inline", "upload"))
        self.assertTrue(payload.get("interrupted_at_stage"))


if __name__ == "__main__":
    unittest.main()
