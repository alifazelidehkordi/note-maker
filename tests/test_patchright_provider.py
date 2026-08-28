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
    UploadRequest,
)
from browser_runtime.errors import (
    BrowserConfigurationError,
    BrowserCrashedError,
    BrowserSendError,
    NetworkUnavailableError,
    RateLimitError,
    UploadCapacityError,
)
from browser_runtime.patchright_provider import (
    RATE_LIMIT_WAIT_SECONDS,
    translate_patchright_error,
)
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
    def __init__(self, candidate=None) -> None:
        self.candidate = candidate

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    @property
    def value(self):
        if self.candidate is not None and self.candidate.clicks == 0:
            raise TimeoutError("synthetic DOM click did not activate the artifact card")
        return FakeDownload()


class Candidate:
    def __init__(self) -> None:
        self.clicks = 0
        self.dom_clicks = 0

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

    def evaluate(self, _expression: str):
        # Mirrors the live regression: HTMLElement.click() can return without
        # opening the artifact preview or starting a download.
        self.dom_clicks += 1


class CandidateCollection:
    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate

    def count(self):
        return 1

    def nth(self, index: int):
        return self.candidate


class UploadInput:
    def __init__(self, page, *, active: bool, upload_enabled: str = "true") -> None:
        self.page = page
        self.active = active
        self.upload_enabled = upload_enabled
        self.values = []

    def get_attribute(self, name: str):
        return {
            "accept": ".md",
            "data-photo-upload-enabled": self.upload_enabled,
        }.get(name, "")

    def is_disabled(self):
        return False

    def set_input_files(self, value):
        self.values.append(value)
        if self.active and value:
            self.page.attached_name = Path(value).name


class UploadInputCollection:
    def __init__(self, items) -> None:
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, index: int):
        return self.items[index]


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
        if selector == "[data-message-author-role='assistant']":
            return AssistantCollection(Assistant(self.candidate))
        if selector == "body":
            return BodyLocator()
        raise AssertionError(selector)

    def expect_download(self, timeout: int):
        return PendingDownload(self.candidate)

    def content(self):
        return "<html><body>ChatGPT</body></html>"

    def screenshot(self, path: str, full_page: bool):
        Path(path).write_bytes(b"png")

    def set_viewport_size(self, _size):
        pass


class StaleUploadInputPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self.attached_name = ""
        # The active composer input is deliberately first so reverse DOM order
        # probes the stale newest input before recovering to the working one.
        self.active_upload = UploadInput(self, active=True)
        self.stale_upload = UploadInput(self, active=False)

    def locator(self, selector: str):
        if selector == "input[type='file']":
            return UploadInputCollection([self.active_upload, self.stale_upload])
        return super().locator(selector)


class CapacityBlockedUploadPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self.attached_name = ""
        self.blocked_upload = UploadInput(
            self,
            active=False,
            upload_enabled="false",
        )

    def locator(self, selector: str):
        if selector == "input[type='file']":
            return UploadInputCollection([self.blocked_upload])
        return super().locator(selector)


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


class DelayedSendButton(SendButton):
    def __init__(self, editor: Editor, *, disabled_checks: int) -> None:
        super().__init__(editor)
        self.disabled_checks = disabled_checks
        self.enabled_checks = 0

    def is_enabled(self):
        self.enabled_checks += 1
        return self.enabled_checks > self.disabled_checks


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
            self.assertEqual(session.raw_handle.candidate.dom_clicks, 0)

    def test_upload_skips_stale_hidden_input_and_uses_active_composer_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "07_porhyria_notes.md"
            source.write_text("# Source\n", encoding="utf-8")
            session = self.build_session(root)
            page = StaleUploadInputPage()
            session._page = page
            with (
                mock.patch.object(session, "_rate_limit_visible", return_value=False),
                mock.patch.object(session, "_upload_pending", return_value=False),
                mock.patch.object(session, "_upload_error_text", return_value=""),
                mock.patch(
                    "browser_runtime.patchright_provider.UPLOAD_INPUT_PROBE_SECONDS",
                    0.01,
                ),
                mock.patch(
                    "browser_runtime.patchright_provider._body_text",
                    side_effect=lambda current_page: current_page.attached_name,
                ),
            ):
                session.upload(UploadRequest(source, timeout=2))
            self.assertTrue(page.stale_upload.values)
            self.assertEqual(page.stale_upload.values[-1], [])
            self.assertEqual(page.active_upload.values, [str(source.resolve())])

    def test_upload_capacity_flag_fails_fast_without_touching_disabled_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "07_porhyria_notes.md"
            source.write_text("# Source\n", encoding="utf-8")
            session = self.build_session(root)
            page = CapacityBlockedUploadPage()
            session._page = page
            with self.assertRaisesRegex(UploadCapacityError, "disabled document uploads") as raised:
                session.upload(UploadRequest(source, timeout=600))
            self.assertEqual(raised.exception.retry_after, 60)
            self.assertEqual(page.blocked_upload.values, [])

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

    def test_send_dismisses_rate_limit_and_requests_global_cooldown(self):
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
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch(
                    "browser_runtime.patchright_provider._first_visible",
                    return_value=button,
                ),
            ):
                with self.assertRaises(RateLimitError) as raised:
                    session.send_message("wait after acknowledgement")
            dismiss.assert_called_once()
            self.assertEqual(button.clicks, 0)
            self.assertEqual(raised.exception.retry_after, RATE_LIMIT_WAIT_SECONDS)

    def test_send_waits_for_attachment_processing_before_clicking(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            editor = Editor()
            button = DelayedSendButton(editor, disabled_checks=2)
            with (
                mock.patch.object(session, "_find_editor", return_value=editor),
                mock.patch.object(session, "_rate_limit_visible", return_value=False),
                mock.patch.object(
                    session, "assistant_message_count", side_effect=[0, 1]
                ),
                mock.patch(
                    "browser_runtime.patchright_provider._first_visible",
                    return_value=button,
                ),
                mock.patch("browser_runtime.patchright_provider.time.sleep"),
            ):
                session.send_message("wait until the attachment is ready")
            self.assertGreaterEqual(button.enabled_checks, 3)
            self.assertEqual(button.clicks, 1)

    def test_send_acknowledgement_accepts_visible_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            editor = Editor()
            button = mock.MagicMock()
            button.is_enabled.return_value = True
            with (
                mock.patch.object(session, "_find_editor", return_value=editor),
                mock.patch.object(session, "_rate_limit_visible", return_value=False),
                mock.patch.object(session, "_generation_visible", return_value=True),
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch(
                    "browser_runtime.patchright_provider._first_visible",
                    return_value=button,
                ),
            ):
                session.send_message("generation is acknowledgement")
            button.evaluate.assert_called_once()

    def test_wait_recurring_rate_limit_requests_cooldown_at_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(session, "_rate_limit_visible", return_value=True),
                mock.patch.object(
                    PatchrightBrowserSession, "_dismiss_rate_limit_modal", return_value=True
                ) as dismiss,
                mock.patch.object(session, "assistant_message_count", return_value=0),
                mock.patch.object(session, "_generation_visible", return_value=False),
            ):
                with self.assertRaises(RateLimitError) as raised:
                    session.wait_for_response(
                        ResponseWaitRequest(min_assistant_count=1, timeout=1)
                    )
            dismiss.assert_called_once()
            self.assertEqual(raised.exception.retry_after, RATE_LIMIT_WAIT_SECONDS)

    def test_rate_limit_phrase_in_page_body_is_not_a_live_modal(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = self.build_session(Path(tmp))
            with (
                mock.patch.object(session, "_visible_rate_limit_dialog", return_value=None),
                mock.patch(
                    "browser_runtime.patchright_provider._body_text",
                    return_value="An old response explains a rate limit algorithm.",
                ),
            ):
                self.assertFalse(session._rate_limit_visible())

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
        self.assertIsInstance(
            translate_patchright_error("wait_response", RuntimeError("Locator.count: Target crashed")),
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
