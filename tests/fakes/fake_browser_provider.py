from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from browser_runtime import (
    BrowserCrashedError,
    BrowserHealth,
    BrowserHealthStatus,
    BrowserLaunchOptions,
    BrowserOperationRecord,
    BrowserResponseTimeout,
    DownloadRequest,
    ResponseWaitRequest,
    UploadRequest,
)


@dataclass
class FakeBrowserPlan:
    download_path: Path | None = None
    assistant_count: int = 0
    response_text: str = "fake assistant response"
    page_source: str = "<html><body>fake browser</body></html>"
    screenshot_bytes: bytes = b"fake-png"
    cookies: list[dict[str, Any]] = field(default_factory=list)
    failures: dict[str, list[BaseException]] = field(default_factory=dict)
    alive: bool = True

    @classmethod
    def timeout(cls) -> "FakeBrowserPlan":
        return cls(
            failures={
                "wait_for_response": [
                    BrowserResponseTimeout("simulated response timeout")
                ]
            }
        )

    @classmethod
    def crash(cls) -> "FakeBrowserPlan":
        return cls(
            failures={"send_message": [BrowserCrashedError("simulated browser crash")]}
        )

    def pop_failure(self, operation: str) -> BaseException | None:
        queued = self.failures.get(operation)
        if not queued:
            return None
        return queued.pop(0)


class FakeBrowserSession:
    provider_name = "fake"

    def __init__(self, plan: FakeBrowserPlan | None = None) -> None:
        self.plan = plan or FakeBrowserPlan()
        self.operations: list[BrowserOperationRecord] = []
        self._raw_handle = object()

    @property
    def raw_handle(self) -> object:
        return self._raw_handle

    def _record(self, operation: str, **payload: Any) -> None:
        self.operations.append(BrowserOperationRecord(operation, payload))
        failure = self.plan.pop_failure(operation)
        if failure is not None:
            raise failure

    def is_alive(self) -> bool:
        self._record("is_alive")
        return self.plan.alive

    def health(self) -> BrowserHealth:
        self._record("health")
        status = BrowserHealthStatus.HEALTHY if self.plan.alive else BrowserHealthStatus.DEAD
        return BrowserHealth(status, "fake health")

    def recover(self, reason: str = "") -> bool:
        self._record("recover", reason=reason)
        self.plan.alive = True
        return True

    def close(self) -> None:
        self._record("close")
        self.plan.alive = False

    def set_window_size(self, width: int, height: int) -> None:
        self._record("set_window_size", width=width, height=height)

    def navigate(self, url: str) -> None:
        self._record("navigate", url=url)

    def wait_until_logged_in(self, timeout: int = 600) -> None:
        self._record("wait_until_logged_in", timeout=timeout)

    def start_new_chat(self) -> None:
        self._record("start_new_chat")

    def select_model(self, model: str | None) -> None:
        self._record("select_model", model=model)

    def assistant_message_count(self) -> int:
        self._record("assistant_message_count")
        return self.plan.assistant_count

    def upload(self, request: UploadRequest) -> None:
        self._record(
            "upload",
            file_path=str(request.file_path),
            native_upload=request.native_upload,
            timeout=request.timeout,
        )

    def send_message(self, text: str) -> None:
        self._record("send_message", text=text)

    def wait_for_response(self, request: ResponseWaitRequest) -> None:
        self._record(
            "wait_for_response",
            min_assistant_count=request.min_assistant_count,
            timeout=request.timeout,
        )

    def snapshot_downloads(self):
        self._record("snapshot_downloads")
        return {"fake": "snapshot"}

    def resolve_download(self, request: DownloadRequest) -> Path | None:
        self._record(
            "resolve_download",
            expected_extensions=sorted(request.expected_extensions),
            started_at_ns=request.started_at_ns,
            timeout=request.timeout,
            click=request.click,
            job_key=request.job_key,
            destination_dir=str(request.destination_dir) if request.destination_dir else None,
        )
        return self.plan.download_path

    def latest_assistant_text(self) -> str:
        self._record("latest_assistant_text")
        return self.plan.response_text

    def save_screenshot(self, path: Path) -> bool:
        self._record("save_screenshot", path=str(path))
        Path(path).write_bytes(self.plan.screenshot_bytes)
        return True

    def get_page_source(self) -> str:
        self._record("get_page_source")
        return self.plan.page_source

    def get_cookies(self) -> Sequence[Mapping[str, Any]]:
        self._record("get_cookies")
        return tuple(dict(item) for item in self.plan.cookies)

    def delete_cookie(self, name: str) -> None:
        self._record("delete_cookie", name=name)
        self.plan.cookies = [item for item in self.plan.cookies if item.get("name") != name]


class FakeBrowserProvider:
    name = "fake"

    def __init__(self, plan: FakeBrowserPlan | None = None) -> None:
        self.plan = plan or FakeBrowserPlan()
        self.sessions: list[FakeBrowserSession] = []
        self.open_options: list[BrowserLaunchOptions] = []

    def open_session(self, options: BrowserLaunchOptions | None = None) -> FakeBrowserSession:
        options = options or BrowserLaunchOptions()
        self.open_options.append(options)
        session = FakeBrowserSession(self.plan)
        self.sessions.append(session)
        session.set_window_size(options.width, options.height)
        if options.url:
            session.navigate(options.url)
        return session

    def wrap_handle(self, handle: object) -> FakeBrowserSession:
        if isinstance(handle, FakeBrowserSession):
            return handle
        raise TypeError("FakeBrowserProvider only wraps FakeBrowserSession values")
