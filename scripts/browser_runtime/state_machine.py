from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    AUTH_CHECK = "auth_check"
    AUTH_REQUIRED = "auth_required"
    READY = "ready"
    UPLOADING = "uploading"
    SENDING = "sending"
    GENERATING = "generating"
    DOWNLOADING = "downloading"
    RECOVERING = "recovering"
    CLOSED = "closed"
    FAILED = "failed"


class ResponseState(str, Enum):
    WAITING = "waiting"
    GENERATING = "generating"
    RATE_LIMITED = "rate_limited"
    DOWNLOAD_READY = "download_ready"
    STABLE = "stable"


@dataclass(frozen=True)
class ResponseObservation:
    assistant_count: int
    generating: bool
    body_text: str
    has_download: bool = False
    rate_limited: bool = False
    now: float = 0.0


class ResponseStateMachine:
    """Small deterministic state machine for response completion detection."""

    def __init__(self, *, required_assistant_count: int | None, stable_seconds: float = 5.0) -> None:
        self.required_assistant_count = required_assistant_count
        self.stable_seconds = stable_seconds
        self._last_text = ""
        self._stable_since: float | None = None
        self._generation_since: float | None = None

    @property
    def generation_since(self) -> float | None:
        return self._generation_since

    def observe(self, observation: ResponseObservation) -> ResponseState:
        now = observation.now
        if observation.rate_limited:
            self._stable_since = None
            return ResponseState.RATE_LIMITED

        response_seen = (
            self.required_assistant_count is None
            or observation.assistant_count >= self.required_assistant_count
        )

        if observation.generating:
            if self._generation_since is None:
                self._generation_since = now
            self._stable_since = None
            self._last_text = observation.body_text
            return ResponseState.GENERATING

        self._generation_since = None
        if response_seen and observation.has_download:
            return ResponseState.DOWNLOAD_READY

        if not response_seen:
            self._stable_since = None
            self._last_text = observation.body_text
            return ResponseState.WAITING

        if observation.body_text == self._last_text:
            if self._stable_since is None:
                self._stable_since = now
            if now - self._stable_since >= self.stable_seconds:
                return ResponseState.STABLE
        else:
            self._stable_since = None
            self._last_text = observation.body_text
        return ResponseState.WAITING
