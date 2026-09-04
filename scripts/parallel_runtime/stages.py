from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable, Iterator

from .event_bus import EventKind, StageEventData, StageKind, StagePhase, utc_now


class StageReporter:
    """Emit structured stage lifecycle events through a worker's existing emitter."""

    def __init__(
        self,
        *,
        emit: Callable[..., None],
        run_id: str,
        worker_id: str,
        source_filename: str,
        clock: Callable[[], float] | None = None,
        timestamp: Callable[[], str] | None = None,
    ) -> None:
        self.emit = emit
        self.run_id = run_id
        self.worker_id = worker_id
        self.source_filename = source_filename
        self._clock = clock or time.monotonic
        self._timestamp = timestamp or utc_now
        self.attempt: int | None = None
        self._stage: StageKind | None = None
        self._stage_attempt: int | None = None
        self._stage_started_at: str | None = None
        self._stage_started_monotonic: float | None = None

    def set_attempt(self, attempt: int | None) -> None:
        self.attempt = None if attempt is None else max(1, int(attempt))

    def browser_stage(self, stage: StageKind) -> None:
        self.transition(stage, attempt=None)

    def content_stage(self, stage: StageKind) -> None:
        # Browser warm-up also calls response-provider methods. Do not label
        # those as source work until the content attempt has actually started.
        if self.attempt is None:
            return
        self.transition(stage, attempt=self.attempt)

    def transition(self, stage: StageKind, *, attempt: int | None) -> None:
        self.complete_current()
        now_text = self._timestamp()
        now_monotonic = self._clock()
        self._stage = stage
        self._stage_attempt = attempt
        self._stage_started_at = now_text
        self._stage_started_monotonic = now_monotonic
        self._emit_stage(
            stage=stage,
            phase=StagePhase.STARTED,
            attempt=attempt,
            started_at=now_text,
            elapsed=0.0,
            activity_at=now_text,
        )

    def complete_current(self) -> None:
        if (
            self._stage is None
            or self._stage_started_at is None
            or self._stage_started_monotonic is None
        ):
            return
        now_text = self._timestamp()
        elapsed = max(0.0, self._clock() - self._stage_started_monotonic)
        self._emit_stage(
            stage=self._stage,
            phase=StagePhase.COMPLETED,
            attempt=self._stage_attempt,
            started_at=self._stage_started_at,
            elapsed=elapsed,
            activity_at=now_text,
        )
        self._stage = None
        self._stage_attempt = None
        self._stage_started_at = None
        self._stage_started_monotonic = None

    def mark_completed(self) -> None:
        self.content_stage(StageKind.COMPLETED)
        self.complete_current()

    def _emit_stage(
        self,
        *,
        stage: StageKind,
        phase: StagePhase,
        attempt: int | None,
        started_at: str,
        elapsed: float,
        activity_at: str,
    ) -> None:
        data = StageEventData(
            run_id=self.run_id,
            worker_id=self.worker_id,
            source_filename=self.source_filename,
            attempt=attempt,
            stage=stage,
            phase=phase,
            stage_started_at=started_at,
            elapsed_seconds=round(elapsed, 6),
            last_activity_at=activity_at,
        )
        self.emit(EventKind.STAGE, **data.to_payload())


class StagedBrowserSession:
    """Provider-neutral observer that reports measurable browser operation stages."""

    def __init__(
        self,
        session,
        reporter_getter: Callable[[], StageReporter | None],
    ) -> None:
        self._session = session
        self._reporter_getter = reporter_getter

    @property
    def provider_name(self) -> str:
        return self._session.provider_name

    @property
    def raw_handle(self) -> object:
        return self._session.raw_handle

    def _reporter(self) -> StageReporter | None:
        return self._reporter_getter()

    def wait_until_logged_in(self, timeout: int = 600) -> None:
        reporter = self._reporter()
        if reporter is not None:
            reporter.browser_stage(StageKind.WAITING_FOR_LOGIN)
        self._session.wait_until_logged_in(timeout)
        reporter = self._reporter()
        if reporter is not None:
            reporter.browser_stage(StageKind.PREPARING_BROWSER)

    def upload(self, request) -> None:
        reporter = self._reporter()
        if reporter is not None:
            reporter.content_stage(StageKind.UPLOADING)
        self._session.upload(request)

    def wait_for_response(self, request) -> None:
        reporter = self._reporter()
        if reporter is not None:
            reporter.content_stage(StageKind.WAITING_FOR_RESPONSE)
        self._session.wait_for_response(request)

    def resolve_download(self, request):
        reporter = self._reporter()
        if reporter is not None:
            reporter.content_stage(StageKind.RESOLVING_DOWNLOAD)
        return self._session.resolve_download(request)

    def __getattr__(self, name: str):
        return getattr(self._session, name)


class StagedBrowserProvider:
    """Wrap an existing provider without changing its public provider contract."""

    def __init__(self, provider, reporter_getter: Callable[[], StageReporter | None]) -> None:
        self._provider = provider
        self._reporter_getter = reporter_getter

    @property
    def name(self) -> str:
        return self._provider.name

    def _wrap(self, session):
        return StagedBrowserSession(session, self._reporter_getter)

    def open_session(self, options=None):
        return self._wrap(self._provider.open_session(options))

    def wrap_handle(self, handle: object):
        return self._wrap(self._provider.wrap_handle(handle))


@contextmanager
def observe_artifact_stages(common_module, reporter: StageReporter) -> Iterator[None]:
    """Observe validation/save boundaries without changing artifact-save semantics.

    The executor is single-job within each worker process, so temporarily wrapping
    these module-local callables cannot affect a sibling worker. The originals are
    restored even when validation or saving raises.
    """

    original_validate = common_module.validate_artifact
    original_fsync = common_module._fsync_file

    def staged_validate(*args, **kwargs):
        reporter.content_stage(StageKind.VALIDATING)
        return original_validate(*args, **kwargs)

    def staged_fsync(path):
        reporter.content_stage(StageKind.SAVING)
        return original_fsync(path)

    common_module.validate_artifact = staged_validate
    common_module._fsync_file = staged_fsync
    try:
        yield
    finally:
        common_module.validate_artifact = original_validate
        common_module._fsync_file = original_fsync
