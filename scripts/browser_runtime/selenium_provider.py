from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import BrowserSession
from .errors import (
    BrowserAuthenticationError,
    BrowserCrashedError,
    BrowserDownloadError,
    BrowserNavigationError,
    BrowserResponseTimeout,
    BrowserRuntimeError,
    BrowserSendError,
    BrowserStartupError,
    BrowserUploadError,
    TemporaryChatError,
)
from .models import (
    BrowserHealth,
    BrowserHealthStatus,
    BrowserLaunchOptions,
    DownloadRequest,
    ResponseWaitRequest,
    UploadRequest,
)


def _core():
    # Deliberately lazy: the legacy compatibility module imports the provider
    # factory, and tests can still patch facade functions during migration.
    import run_chatgpt_temporary_test as core

    return core


def translate_legacy_error(operation: str, exc: BaseException) -> BrowserRuntimeError:
    if isinstance(exc, BrowserRuntimeError):
        return exc
    message = str(exc)
    lowered = message.lower()
    if any(token in lowered for token in ('disconnected', 'invalid session id', 'chrome not reachable', 'target window already closed')):
        error_type = BrowserCrashedError
    elif 'temporary chat' in lowered or 'prompt editor' in lowered:
        error_type = TemporaryChatError
    elif operation == 'start':
        error_type = BrowserStartupError
    elif operation == 'authenticate':
        error_type = BrowserAuthenticationError
    elif operation in {'navigate', 'new_chat', 'select_model'}:
        error_type = BrowserNavigationError
    elif operation == 'upload':
        error_type = BrowserUploadError
    elif operation == 'send':
        error_type = BrowserSendError
    elif operation == 'wait_response':
        error_type = BrowserResponseTimeout
    elif operation == 'download':
        error_type = BrowserDownloadError
    else:
        error_type = BrowserRuntimeError
    return error_type(f'{operation} failed: {message}')


class SeleniumBrowserSession:
    provider_name = 'selenium'

    def __init__(self, handle: object) -> None:
        self._handle = handle

    @property
    def raw_handle(self) -> object:
        return self._handle

    def _call(self, operation: str, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            raise translate_legacy_error(operation, exc) from exc

    def is_alive(self) -> bool:
        try:
            _ = self._handle.title
            return True
        except Exception:
            return False

    def health(self) -> BrowserHealth:
        if self.is_alive():
            current_url = None
            try:
                current_url = str(getattr(self._handle, 'current_url', '') or '') or None
            except Exception:
                pass
            return BrowserHealth(BrowserHealthStatus.HEALTHY, current_url=current_url)
        return BrowserHealth(BrowserHealthStatus.DEAD, 'Selenium driver is not reachable.')

    def recover(self, reason: str = "") -> bool:
        if not self.is_alive():
            return False
        try:
            refresh = getattr(self._handle, 'refresh', None)
            if refresh is not None:
                self._call('navigate', refresh)
            return self.is_alive()
        except BrowserRuntimeError:
            return False

    def close(self) -> None:
        try:
            quit_method = getattr(self._handle, 'quit', None)
            if quit_method is not None:
                quit_method()
        except Exception:
            pass

    def set_window_size(self, width: int, height: int) -> None:
        method = getattr(self._handle, 'set_window_size', None)
        if method is not None:
            self._call('navigate', method, width, height)

    def navigate(self, url: str) -> None:
        self._call('navigate', self._handle.get, url)

    def wait_until_logged_in(self, timeout: int = 600) -> None:
        self._call('authenticate', _core().wait_until_logged_in, self._handle, timeout=timeout)

    def start_new_chat(self) -> None:
        self._call('new_chat', _core().start_new_chat, self._handle)

    def select_model(self, model: str | None) -> None:
        if model:
            self._call('select_model', _core().select_model, self._handle, model)

    def assistant_message_count(self) -> int:
        return int(self._call('wait_response', _core().assistant_message_count, self._handle))

    def upload(self, request: UploadRequest) -> None:
        if not request.file_path.exists():
            raise BrowserUploadError(f'Upload source does not exist: {request.file_path}')
        self._call(
            'upload',
            _core().attach_file,
            self._handle,
            request.file_path,
            native_upload=request.native_upload,
        )
        self._call(
            'upload',
            _core().wait_for_file_upload_complete,
            self._handle,
            request.file_path,
            timeout=request.timeout,
        )

    def send_message(self, text: str) -> None:
        self._call('send', _core().send_message, self._handle, text)

    def wait_for_response(self, request: ResponseWaitRequest) -> None:
        self._call(
            'wait_response',
            _core().wait_until_idle,
            self._handle,
            timeout=request.timeout,
            min_assistant_count=request.min_assistant_count,
        )

    def snapshot_downloads(self):
        return self._call('download', _core().snapshot_downloads)

    def resolve_download(self, request: DownloadRequest) -> Path | None:
        kwargs = {
            'expected_extensions': set(request.expected_extensions),
            'started_at_ns': request.started_at_ns,
            'timeout': request.timeout,
        }
        if not request.click:
            kwargs['click'] = False
        result = self._call(
            'download',
            _core().resolve_download,
            self._handle,
            request.before,
            **kwargs,
        )
        return Path(result) if result is not None else None

    def latest_assistant_text(self) -> str:
        return str(self._call('wait_response', _core().latest_assistant_text, self._handle))

    def save_screenshot(self, path: Path) -> bool:
        method = getattr(self._handle, 'save_screenshot', None)
        if method is None:
            return False
        return bool(self._call('diagnostics', method, str(path)))

    def get_page_source(self) -> str:
        try:
            return str(self._handle.page_source)
        except Exception as exc:
            raise translate_legacy_error('diagnostics', exc) from exc

    def get_cookies(self) -> Sequence[Mapping[str, Any]]:
        method = getattr(self._handle, 'get_cookies', None)
        if method is None:
            return ()
        return tuple(self._call('cookies', method))

    def delete_cookie(self, name: str) -> None:
        method = getattr(self._handle, 'delete_cookie', None)
        if method is not None:
            self._call('cookies', method, name)


class SeleniumProvider:
    name = 'selenium'

    def open_session(self, options: BrowserLaunchOptions | None = None) -> SeleniumBrowserSession:
        options = options or BrowserLaunchOptions()
        core = _core()
        try:
            # Legacy download helpers consult the facade-level DOWNLOAD_DIR.
            # Each coordinator worker is a separate process, so point that
            # facade at this worker's managed download directory before launch.
            if options.download_dir is not None:
                core.DOWNLOAD_DIR = Path(options.download_dir).expanduser().resolve()
            builder = getattr(core, "_build_driver_with_paths", None)
            if builder is None:
                handle = core.build_driver(headless=options.headless, browser=options.browser)
            else:
                handle = builder(
                    headless=options.headless,
                    browser=options.browser,
                    profile_dir=options.profile_dir,
                    download_dir=options.download_dir,
                )
        except Exception as exc:
            raise translate_legacy_error('start', exc) from exc
        session = SeleniumBrowserSession(handle)
        session.set_window_size(options.width, options.height)
        if options.url:
            session.navigate(options.url)
        return session

    def wrap_handle(self, handle: object) -> BrowserSession:
        if isinstance(handle, SeleniumBrowserSession):
            return handle
        return SeleniumBrowserSession(handle)
