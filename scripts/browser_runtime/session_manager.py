from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import BrowserProvider, BrowserSession
from .models import (
    BrowserHealth,
    BrowserLaunchOptions,
    DownloadRequest,
    ResponseWaitRequest,
    UploadRequest,
)
from .profile_manager import ProfileLease, ProfileManager, WorkerProfileContext


class ManagedBrowserSession:
    """BrowserSession wrapper that owns and releases a profile lease."""

    def __init__(
        self,
        session: BrowserSession,
        *,
        profile_manager: ProfileManager,
        profile_context: WorkerProfileContext,
        lease: ProfileLease,
    ) -> None:
        self._session = session
        self.profile_manager = profile_manager
        self.profile_context = profile_context
        self._lease = lease
        self._closed = False

    @property
    def provider_name(self) -> str:
        return self._session.provider_name

    @property
    def raw_handle(self) -> object:
        return self._session.raw_handle

    @property
    def profile_dir(self) -> Path:
        return self.profile_context.profile_dir

    @property
    def download_dir(self) -> Path:
        return self.profile_context.download_dir

    def is_alive(self) -> bool:
        return self._session.is_alive()

    def health(self) -> BrowserHealth:
        return self._session.health()

    def recover(self, reason: str = "") -> bool:
        return self._session.recover(reason)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._session.close()
        finally:
            self._lease.release()

    def set_window_size(self, width: int, height: int) -> None:
        self._session.set_window_size(width, height)

    def navigate(self, url: str) -> None:
        self._session.navigate(url)

    def wait_until_logged_in(self, timeout: int = 600) -> None:
        self._session.wait_until_logged_in(timeout)

    def start_new_chat(self) -> None:
        self._session.start_new_chat()

    def select_model(self, model: str | None) -> None:
        self._session.select_model(model)

    def assistant_message_count(self) -> int:
        return self._session.assistant_message_count()

    def upload(self, request: UploadRequest) -> None:
        self._session.upload(request)

    def send_message(self, text: str) -> None:
        self._session.send_message(text)

    def wait_for_response(self, request: ResponseWaitRequest) -> None:
        self._session.wait_for_response(request)

    def snapshot_downloads(self) -> Any:
        return self._session.snapshot_downloads()

    def resolve_download(self, request: DownloadRequest) -> Path | None:
        return self._session.resolve_download(request)

    def latest_assistant_text(self) -> str:
        return self._session.latest_assistant_text()

    def save_screenshot(self, path: Path) -> bool:
        return self._session.save_screenshot(path)

    def get_page_source(self) -> str:
        return self._session.get_page_source()

    def get_cookies(self) -> Sequence[Mapping[str, Any]]:
        return self._session.get_cookies()

    def delete_cookie(self, name: str) -> None:
        self._session.delete_cookie(name)

    def dismiss_rate_limit_modal(self) -> bool:
        dismiss = getattr(self._session, "dismiss_rate_limit_modal", None)
        return bool(dismiss()) if callable(dismiss) else False


class SessionBootstrapper:
    def __init__(self, *, profile_manager: ProfileManager) -> None:
        self.profile_manager = profile_manager

    def open_session(
        self,
        *,
        provider: BrowserProvider,
        context: WorkerProfileContext,
        options: BrowserLaunchOptions,
        validate_login: bool = True,
        login_timeout: int = 600,
        before_open: Callable[[WorkerProfileContext], None] | None = None,
    ) -> ManagedBrowserSession:
        lease = self.profile_manager.acquire(context)
        session: BrowserSession | None = None
        try:
            if before_open is not None:
                before_open(context)
            effective_options = replace(
                options,
                profile_dir=context.profile_dir,
                download_dir=context.download_dir,
            )
            session = provider.open_session(effective_options)
            managed = ManagedBrowserSession(
                session,
                profile_manager=self.profile_manager,
                profile_context=context,
                lease=lease,
            )
            if validate_login:
                managed.wait_until_logged_in(timeout=login_timeout)
            return managed
        except Exception:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
            lease.release()
            raise

    def prepare_and_open(
        self,
        *,
        provider: BrowserProvider,
        run_id: str,
        worker_id: str,
        snapshot: str | Path,
        options: BrowserLaunchOptions,
        validate_login: bool = True,
        login_timeout: int = 600,
        recreate: bool = False,
    ) -> ManagedBrowserSession:
        context = self.profile_manager.prepare_worker(
            run_id=run_id,
            worker_id=worker_id,
            snapshot=snapshot,
            recreate=recreate,
        )
        return self.open_session(
            provider=provider,
            context=context,
            options=options,
            validate_login=validate_login,
            login_timeout=login_timeout,
        )
