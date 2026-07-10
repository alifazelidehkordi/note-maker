from __future__ import annotations

import inspect
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import run_chatgpt_temporary_test as facade
from browser_runtime import (
    BrowserConfigurationError,
    BrowserCrashedError,
    BrowserDownloadError,
    BrowserProvider,
    BrowserResponseTimeout,
    BrowserSession,
    DownloadRequest,
    ResponseWaitRequest,
    PatchrightProvider,
    SeleniumProvider,
    UploadRequest,
    create_browser_provider,
)
from browser_runtime.selenium_provider import translate_legacy_error
from tests.fakes.fake_browser_provider import FakeBrowserProvider, FakeBrowserSession


class RawHandle:
    title = "ChatGPT"
    page_source = "<html></html>"

    def __init__(self) -> None:
        self.closed = False
        self.urls: list[str] = []

    def set_window_size(self, _width: int, _height: int) -> None:
        pass

    def get(self, url: str) -> None:
        self.urls.append(url)

    def quit(self) -> None:
        self.closed = True

    def save_screenshot(self, path: str) -> bool:
        Path(path).write_bytes(b"png")
        return True

    def get_cookies(self):
        return []


class BrowserRuntimeContractTests(unittest.TestCase):
    def test_fake_provider_and_session_satisfy_runtime_protocols(self):
        provider = FakeBrowserProvider()
        session = provider.open_session()
        self.assertIsInstance(provider, BrowserProvider)
        self.assertIsInstance(session, BrowserSession)

    def test_factory_returns_supported_providers_and_rejects_unknown_provider(self):
        self.assertIsInstance(create_browser_provider("selenium"), SeleniumProvider)
        self.assertIsInstance(create_browser_provider("patchright"), PatchrightProvider)
        with self.assertRaises(BrowserConfigurationError):
            create_browser_provider("unknown")

    def test_request_models_normalize_extensions_and_validate_timeouts(self):
        request = DownloadRequest({}, {"MD", ".opml"}, started_at_ns=1)
        self.assertEqual(request.expected_extensions, frozenset({".md", ".opml"}))
        with self.assertRaises(ValueError):
            ResponseWaitRequest(timeout=0)
        with self.assertRaises(ValueError):
            UploadRequest(Path("source.pdf"), timeout=0)

    def test_selenium_session_delegates_high_level_operations_to_facade(self):
        raw = RawHandle()
        session = SeleniumProvider().wrap_handle(raw)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdf"
            source.write_bytes(b"pdf")
            downloaded = Path(tmp) / "result.md"
            with mock.patch.object(facade, "start_new_chat") as start, mock.patch.object(
                facade, "select_model"
            ) as select, mock.patch.object(facade, "attach_file") as attach, mock.patch.object(
                facade, "wait_for_file_upload_complete"
            ) as uploaded, mock.patch.object(
                facade, "assistant_message_count", return_value=2
            ), mock.patch.object(
                facade, "send_message"
            ) as send, mock.patch.object(
                facade, "wait_until_idle"
            ) as idle, mock.patch.object(
                facade, "snapshot_downloads", return_value={"before": 1}
            ), mock.patch.object(
                facade, "resolve_download", return_value=downloaded
            ) as resolve:
                session.start_new_chat()
                session.select_model("GPT Test")
                session.upload(UploadRequest(source))
                self.assertEqual(session.assistant_message_count(), 2)
                session.send_message("prompt")
                session.wait_for_response(ResponseWaitRequest(min_assistant_count=3, timeout=9))
                before = session.snapshot_downloads()
                result = session.resolve_download(
                    DownloadRequest(before, {"md"}, started_at_ns=12, timeout=7)
                )

            start.assert_called_once_with(raw)
            select.assert_called_once_with(raw, "GPT Test")
            attach.assert_called_once_with(raw, source.resolve(), native_upload=False)
            uploaded.assert_called_once_with(raw, source.resolve(), timeout=600)
            send.assert_called_once_with(raw, "prompt")
            idle.assert_called_once_with(raw, timeout=9, min_assistant_count=3)
            resolve.assert_called_once_with(
                raw,
                {"before": 1},
                expected_extensions={".md"},
                started_at_ns=12,
                timeout=7,
            )
            self.assertEqual(result, downloaded)

    def test_legacy_errors_are_translated_to_typed_runtime_errors(self):
        self.assertIsInstance(
            translate_legacy_error("wait_response", TimeoutError("late")),
            BrowserResponseTimeout,
        )
        self.assertIsInstance(
            translate_legacy_error("send", RuntimeError("invalid session id")),
            BrowserCrashedError,
        )
        self.assertIsInstance(
            translate_legacy_error("download", RuntimeError("missing")),
            BrowserDownloadError,
        )

    def test_facade_preserves_legacy_signatures(self):
        self.assertEqual(
            str(inspect.signature(facade.resolve_download)),
            str(inspect.signature(facade._ORIGINALS["resolve_download"])),
        )
        self.assertEqual(
            str(inspect.signature(facade.build_driver)),
            str(inspect.signature(facade._ORIGINALS["build_driver"])),
        )


if __name__ == "__main__":
    unittest.main()
