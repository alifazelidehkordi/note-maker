from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from browser_runtime import (
    BrowserHealthStatus,
    BrowserLaunchOptions,
    BrowserSession,
    DownloadRequest,
    PatchrightBrowserSession,
    ResponseWaitRequest,
)
from browser_runtime.errors import (
    BrowserConfigurationError,
    BrowserCrashedError,
    BrowserSendError,
    NetworkUnavailableError,
    RateLimitError,
)
from browser_runtime.patchright_provider import (
    RATE_LIMIT_WAIT_SECONDS,
    translate_patchright_error,
)
from browser_runtime.selectors import ASSISTANT_MESSAGE_SELECTOR

DIALOG_SELECTORS = {
    "#modal-conversation-history-rate-limit",
    "[role='dialog']",
    "[data-testid*='rate-limit' i]",
    "[data-radix-portal] [role='dialog']",
}
from artifact_validation import validate_artifact


class FakePlaywright:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class FakeDownload:
    suggested_filename = "generated.md"

    def save_as(self, path: str) -> None:
        Path(path).write_text(
            "# Generated Note\n\n## Explanation\n\n"
            "This deterministic Patchright download contains enough meaningful "
            "content to pass the existing Markdown artifact validator without "
            "special treatment in the browser provider.\n",
            encoding="utf-8",
        )


class PendingDownload:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def value(self):
        return FakeDownload()


class Candidate:
    def __init__(self) -> None:
        self.clicks = 0

    def is_visible(self, timeout=0):
        return True

    def inner_text(self):
        return "Download Markdown file"

    def get_attribute(self, name: str):
        return {"href": "sandbox:/mnt/data/generated.md"}.get(name, "")

    def scroll_into_view_if_needed(self):
        pass

    def click(self):
        self.clicks += 1


class CandidateCollection:
    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def count(self):
        return 1

    def nth(self, index: int):
        return self.candidate


class Assistant:
    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def inner_text(self):
        return "The Markdown artifact is ready for download."

    def locator(self, _selector: str):
        return CandidateCollection(self.candidate)


class AssistantCollection:
    def __init__(self, assistant: Assistant) -> None:
        self.assistant = assistant

    def count(self):
        return 1

    def nth(self, index: int):
        return self.assistant

    @property
    def last(self):
        return self.assistant


class BodyLocator:
    def inner_text(self, timeout=0):
        return "ChatGPT"


class EmptyCollection:
    """Locator stand-in for dialog queries that match nothing on the fake page."""

    def count(self) -> int:
        return 0

    def nth(self, _index: int):  # pragma: no cover - never reached when count()==0
        raise AssertionError("nth() on empty collection")


class FakePage:
    url = "https://chatgpt.com/"

    def __init__(self) -> None:
        self.candidate = Candidate()
        self.closed = False
        self.handlers = {}

    def on(self, event: str, handler):
        self.handlers[event] = handler

    def is_closed(self):
        return self.closed

    def locator(self, selector: str):
        if selector == ASSISTANT_MESSAGE_SELECTOR:
            return AssistantCollection(Assistant(self.candidate))
        if selector == "body":
            return BodyLocator()
        if selector in DIALOG_SELECTORS:
            return EmptyCollection()
        raise AssertionError(selector)

    def expect_download(self, timeout: int):
        return PendingDownload()

    def content(self):
        return "<html><body>ChatGPT</body></html>"

    def screenshot(self, path: str, full_page: bool):
        Path(path).write_bytes(b"png")

    def set_viewport_size(self, _size):
        pass


class FakeContext:
    def __init__(self) -> None:
        self.closed = False
        self.cookie_items = [{"name": "keep"}, {"name": "drop"}]

    def cookies(self):
        return list(self.cookie_items)

    def clear_cookies(self):
        self.cookie_items = []

    def add_cookies(self, cookies):
        self.cookie_items = list(cookies)

    def close(self):
        self.closed = True


class Editor:
    def __init__(self) -> None:
        self.text = ""

    def input_value(self):
        return self.text

    def fill(self, text: str):
        self.text = text


class SendButton:
    def __init__(self, editor: Editor) -> None:
        self.editor = editor
        self.clicks = 0

    def is_enabled(self):
        return True

    def click(self):
        self.clicks += 1
        self.editor.text = ""


class PatchrightProviderTests(unittest.TestCase):
    def build_session(self, root: Path) -> PatchrightBrowserSession:
        return PatchrightBrowserSession(
            playwright=FakePlaywright(),
            context=FakeContext(),
            page=FakePage(),
            options=BrowserLaunchOptions(download_dir=root),
            profile_dir=root / "profile",
            download_dir=root,
        )

    def test_patchright_session_satisfies_browser_contract_and_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            self.assertIsInstance(session, BrowserSession)
            self.assertEqual(session.health().status, BrowserHealthStatus.HEALTHY)
            session.delete_cookie("drop")
            self.assertEqual([item["name"] for item in session.get_cookies()], ["keep"])

    def test_page_crash_event_marks_session_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            session.raw_handle.handlers["crash"]()
            self.assertFalse(session.is_alive())
            self.assertEqual(session.health().status, BrowserHealthStatus.DEAD)

    def test_rate_limit_modal_uses_dom_click_and_verifies_dismissal(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            dialog = mock.MagicMock()
            button = mock.MagicMock()
            dialog.get_by_role.return_value.first = button
            button.is_visible.return_value = True
            with (
                mock.patch.object(
                    session,
                    "_rate_limit_visible",
                    side_effect=[True, False],
                ),
                mock.patch.object(
                    session,
                    "_visible_rate_limit_dialog",
                    return_value=dialog,
                ),
            ):
                self.assertTrue(session._dismiss_rate_limit_modal())
            button.evaluate.assert_called_once_with("(element) => element.click()")

    def test_download_uses_event_first_and_job_specific_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.build_session(root)
            result = session.resolve_download(
                DownloadRequest(
                    before={},
                    expected_extensions={".md"},
                    started_at_ns=1,
                    timeout=1,
                    job_key="section/01",
                )
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.parent.name, "section_01")
            self.assertTrue(result.exists())
            self.assertTrue(validate_artifact(result, {".md"}).valid)
            self.assertEqual(session.raw_handle.candidate.clicks, 1)

    def test_send_idempotency_prevents_duplicate_click_after_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            editor = Editor()
            button = SendButton(editor)
            with mock.patch.object(session, "_find_editor", return_value=editor), mock.patch.object(
                session, "_rate_limit_visible", return_value=False
            ), mock.patch.object(
                session, "assistant_message_count", side_effect=[0, 1, 1]
            ), mock.patch(
                "browser_runtime.patchright_provider._first_visible", return_value=button
            ):
                session.send_message("same prompt")
                session.send_message("same prompt")
            self.assertEqual(button.clicks, 1)

    def test_send_acknowledges_visible_rate_limit_and_continues_without_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            editor = Editor()
            button = SendButton(editor)
            with (
                mock.patch.object(session, "_find_editor", return_value=editor),
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ) as dismiss,
                mock.patch.object(
                    session, "assistant_message_count", side_effect=[0, 1]
                ),
                mock.patch(
                    "browser_runtime.patchright_provider._first_visible",
                    return_value=button,
                ),
            ):
                session.send_message("continue despite modal")
            dismiss.assert_called_once()
            self.assertEqual(button.clicks, 1)

    def test_send_raises_rate_limit_when_modal_cannot_be_dismissed(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            editor = Editor()
            button = SendButton(editor)
            with (
                mock.patch.object(session, "_find_editor", return_value=editor),
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=False
                ),
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch(
                    "browser_runtime.patchright_provider._first_visible",
                    return_value=button,
                ),
            ):
                with self.assertRaisesRegex(RateLimitError, "remained visible"):
                    session.send_message("blocked by persistent modal")
            self.assertEqual(button.clicks, 0)

    def test_wait_tolerates_transient_dismissed_rate_limit_modal(self):
        """Two consecutive rate-limit observations that dismiss successfully
        continue the wait; a later stable observation completes normally."""
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            # observations: rl(visible, dismiss ok), rl(visible, dismiss ok),
            # then non-rl (resets counter), then stable completion
            with (
                mock.patch.object(
                    session, "_rate_limit_visible", side_effect=[True, True] + [False] * 50
                ),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ) as dismiss,
                mock.patch.object(
                    session, "assistant_message_count", side_effect=[0, 0, 0, 1, 1, 1]
                ),
                mock.patch.object(session, "_generation_visible", return_value=False),
                mock.patch.object(session, "_download_candidate_exists", return_value=True),
                mock.patch(
                    "browser_runtime.patchright_provider._body_text",
                    return_value="stable body",
                ),
                mock.patch("browser_runtime.patchright_provider.time.monotonic") as mono,
            ):
                # stable_seconds requires >=5s between identical observations
                mono.side_effect = [0, 1, 2, 3, 4, 10, 11, 12, 13, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160]
                session.wait_for_response(
                    ResponseWaitRequest(min_assistant_count=1, timeout=120)
                )
            self.assertEqual(dismiss.call_count, 2)

    def test_wait_raises_after_bounded_consecutive_rate_limit_rechecks(self):
        """Modal dismisses (acknowledged) but persists: 3 consecutive
        RATE_LIMITED observations raise RateLimitError with retry_after."""
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(
                    session, "_rate_limit_visible", side_effect=[True] * 50
                ),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ),
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch.object(session, "_generation_visible", return_value=False),
                mock.patch("browser_runtime.patchright_provider.time.sleep"),
                mock.patch("browser_runtime.patchright_provider.time.monotonic") as mono,
            ):
                mono.side_effect = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
                with self.assertRaisesRegex(RateLimitError, "acknowledged") as raised:
                    session.wait_for_response(
                        ResponseWaitRequest(min_assistant_count=1, timeout=120)
                    )
            self.assertEqual(raised.exception.retry_after, RATE_LIMIT_WAIT_SECONDS)

    def test_wait_resets_recheck_counter_on_non_rate_limited_observation(self):
        """rl, rl, non-rl (reset), rl, rl, rl -> only the 3 consecutive AFTER
        the reset raise; total dismissals = 5 not 3+2 (counter reset proof)."""
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(
                    session,
                    "_rate_limit_visible",
                    side_effect=[True, True, False, True, True, True] + [True] * 50,
                ),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ),
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch.object(session, "_generation_visible", return_value=False),
                mock.patch("browser_runtime.patchright_provider.time.sleep"),
                mock.patch("browser_runtime.patchright_provider.time.monotonic") as mono,
            ):
                mono.side_effect = list(range(200))
                with self.assertRaisesRegex(RateLimitError, "acknowledged"):
                    session.wait_for_response(
                        ResponseWaitRequest(min_assistant_count=1, timeout=120)
                    )

    def test_download_miss_raises_rate_limit_when_modal_visible(self):
        """A rate-limit modal visible during a failed download attempt must
        raise RateLimitError, not be misclassified as a download failure."""
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(
                    session, "_find_download_candidates", return_value=[(0, mock.MagicMock())]
                ),
                mock.patch.object(
                    session, "_page", **{"expect_download.side_effect": RuntimeError("miss")}
                ),
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ),
            ):
                with self.assertRaisesRegex(RateLimitError, "artifact download"):
                    session.resolve_download(
                        DownloadRequest(
                            before={},
                            expected_extensions={".md"},
                            started_at_ns=1,
                            timeout=1,
                            job_key="section/01",
                        )
                    )

    def test_wait_raises_rate_limit_when_modal_cannot_be_dismissed(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=False
                ),
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch.object(session, "_generation_visible", return_value=False),
            ):
                with self.assertRaisesRegex(RateLimitError, "remained visible"):
                    session.wait_for_response(
                        ResponseWaitRequest(min_assistant_count=1, timeout=1)
                    )

    def test_uncertain_send_blocks_a_second_click_for_same_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            prompt = "same prompt"
            session._last_send_hash = session._prompt_hash(prompt)
            session._last_send_assistant_count = 0
            session._last_send_completed = False
            session._last_send_started_at = 100.0

            with mock.patch(
                "browser_runtime.patchright_provider.time.monotonic",
                return_value=120.0,
            ), mock.patch.object(
                session, "assistant_message_count", return_value=0
            ), mock.patch.object(
                session, "_generation_visible", return_value=False
            ), mock.patch.object(
                session, "_find_editor", side_effect=AssertionError("must not edit or click")
            ):
                with self.assertRaisesRegex(BrowserSendError, "duplicate click was blocked"):
                    session.send_message(prompt)

    def test_patchright_errors_map_to_typed_runtime_taxonomy(self):
        self.assertIsInstance(
            translate_patchright_error("navigate", RuntimeError("net::ERR_INTERNET_DISCONNECTED")),
            NetworkUnavailableError,
        )
        self.assertIsInstance(
            translate_patchright_error("send", RuntimeError("Too many requests / rate limit")),
            RateLimitError,
        )
        self.assertIsInstance(
            translate_patchright_error("send", RuntimeError("Target page, context or browser has been closed")),
            BrowserCrashedError,
        )
        sandbox_error = translate_patchright_error(
            "start",
            RuntimeError(
                "browser closed; crashpad setsockopt: Operation not permitted; signal=SIGTRAP"
            ),
        )
        self.assertIsInstance(sandbox_error, BrowserConfigurationError)
        self.assertIn("host sandbox/security policy", str(sandbox_error))


if __name__ == "__main__":
    unittest.main()
