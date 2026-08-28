from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping

from browser_runtime.errors import (
    BrowserAuthenticationError,
    BrowserConfigurationError,
    BrowserCrashedError,
    BrowserDownloadError,
    BrowserNavigationError,
    BrowserResponseTimeout,
    BrowserSendError,
    BrowserUploadError,
    PageStateError,
    BrowserRuntimeError,
    BrowserStartupError,
    NetworkUnavailableError,
    ProfileRuntimeError,
    RateLimitError,
)


class FailureCategory(str, Enum):
    CONTENT = "content"
    NETWORK = "network"
    BROWSER = "browser"
    DOWNLOAD = "download"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    UNKNOWN = "unknown"


def classify_failure(error: BaseException | str | None) -> FailureCategory:
    """Map provider/runtime failures to stable retry-budget categories."""
    if error is None:
        return FailureCategory.UNKNOWN
    if isinstance(error, str):
        lowered = error.lower()
        if "rate limit" in lowered or "too many requests" in lowered:
            return FailureCategory.RATE_LIMIT
        if "auth" in lowered or "login" in lowered or "cloudflare" in lowered:
            return FailureCategory.AUTH
        if "network" in lowered or "connection" in lowered or "dns" in lowered:
            return FailureCategory.NETWORK
        if "download" in lowered or "artifact" in lowered:
            return FailureCategory.DOWNLOAD
        if "browser" in lowered or "chromium" in lowered or "profile" in lowered:
            return FailureCategory.BROWSER
        return FailureCategory.UNKNOWN
    if isinstance(error, BrowserAuthenticationError):
        return FailureCategory.AUTH
    if isinstance(error, RateLimitError):
        return FailureCategory.RATE_LIMIT
    if isinstance(error, NetworkUnavailableError):
        return FailureCategory.NETWORK
    if isinstance(
        error,
        (BrowserConfigurationError, BrowserCrashedError, BrowserStartupError, ProfileRuntimeError),
    ):
        return FailureCategory.BROWSER
    if isinstance(error, BrowserDownloadError):
        return FailureCategory.DOWNLOAD
    if isinstance(error, (BrowserResponseTimeout, BrowserSendError, BrowserUploadError, PageStateError)):
        return FailureCategory.CONTENT
    if isinstance(error, BrowserNavigationError):
        return FailureCategory.NETWORK
    if error.__class__.__name__ in {"NoValidArtifactError", "ArtifactValidationError"}:
        return FailureCategory.CONTENT
    if isinstance(error, (ConnectionError, TimeoutError, OSError)):
        return FailureCategory.NETWORK
    if isinstance(error, BrowserRuntimeError):
        return FailureCategory.CONTENT
    return FailureCategory.UNKNOWN


@dataclass(frozen=True)
class RetryBudgetPolicy:
    """Independent retry ceilings. Values are retry counts, except content_attempts."""

    content_attempts: int = 3
    network_retries: int = 4
    browser_retries: int = 3
    download_retries: int = 2
    rate_limit_retries: int = 2
    backoff_base: float = 3.0
    backoff_cap: float = 24.0
    jitter_ratio: float = 0.20

    def __post_init__(self) -> None:
        for name in (
            "content_attempts",
            "network_retries",
            "browser_retries",
            "download_retries",
            "rate_limit_retries",
        ):
            if int(getattr(self, name)) < (1 if name == "content_attempts" else 0):
                raise ValueError(f"{name} has an invalid retry limit.")
        if self.backoff_base < 0 or self.backoff_cap < 0:
            raise ValueError("Retry backoff values must not be negative.")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1.")

    @property
    def maximum_total_attempts(self) -> int:
        return max(
            1,
            self.content_attempts
            + self.network_retries
            + self.browser_retries
            + self.download_retries
            + self.rate_limit_retries,
        )

    def limit_for(self, category: FailureCategory) -> int:
        if category in {FailureCategory.CONTENT, FailureCategory.UNKNOWN}:
            return self.content_attempts
        return {
            FailureCategory.NETWORK: self.network_retries,
            FailureCategory.BROWSER: self.browser_retries,
            FailureCategory.DOWNLOAD: self.download_retries,
            FailureCategory.RATE_LIMIT: self.rate_limit_retries,
            FailureCategory.AUTH: 0,
        }[category]

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object] | None,
        *,
        content_attempts: int = 3,
    ) -> "RetryBudgetPolicy":
        source = dict(values or {})
        return cls(
            content_attempts=int(source.get("content_attempts", content_attempts)),
            network_retries=int(source.get("network_retries", 4)),
            browser_retries=int(source.get("browser_retries", 3)),
            download_retries=int(source.get("download_retries", 2)),
            rate_limit_retries=int(source.get("rate_limit_retries", 2)),
            backoff_base=float(source.get("backoff_base", 3.0)),
            backoff_cap=float(source.get("backoff_cap", 24.0)),
            jitter_ratio=float(source.get("jitter_ratio", 0.20)),
        )


@dataclass(frozen=True)
class RetryDecision:
    category: FailureCategory
    count: int
    limit: int
    retry: bool
    delay_seconds: float
    retry_after: float | None = None


@dataclass
class RetryTracker:
    policy: RetryBudgetPolicy
    seed: int | str | None = None
    counts: Counter[str] = field(default_factory=Counter)
    total_failures: int = 0
    last_category: FailureCategory | None = None
    last_decision: RetryDecision | None = None

    def _delay(
        self,
        category: FailureCategory,
        count: int,
        *,
        retry_after: float | None,
        default_delay: float,
    ) -> float:
        if retry_after is not None:
            base = max(0.0, float(retry_after))
        elif category in {
            FailureCategory.NETWORK,
            FailureCategory.BROWSER,
            FailureCategory.DOWNLOAD,
            FailureCategory.RATE_LIMIT,
        }:
            base = min(
                self.policy.backoff_cap,
                self.policy.backoff_base * (2 ** max(0, count - 1)),
            )
        else:
            base = max(0.0, float(default_delay))
        if base == 0 or self.policy.jitter_ratio == 0:
            return base
        rng = random.Random(f"{self.seed}:{category.value}:{count}")
        factor = 1.0 + rng.uniform(-self.policy.jitter_ratio, self.policy.jitter_ratio)
        return max(0.0, base * factor)

    def record(
        self,
        error: BaseException,
        *,
        default_delay: float = 0.0,
    ) -> RetryDecision:
        category = classify_failure(error)
        key = category.value
        self.counts[key] += 1
        self.total_failures += 1
        self.last_category = category
        count = self.counts[key]
        limit = self.policy.limit_for(category)
        retry_after_value = getattr(error, "retry_after", None)
        retry_after = (
            float(retry_after_value) if retry_after_value is not None else None
        )
        if category in {FailureCategory.CONTENT, FailureCategory.UNKNOWN}:
            retry = count < limit
        else:
            retry = count <= limit
        if category == FailureCategory.AUTH:
            retry = False
        if isinstance(error, BrowserConfigurationError):
            retry = False
        decision = RetryDecision(
            category=category,
            count=count,
            limit=limit,
            retry=retry,
            delay_seconds=(
                self._delay(
                    category,
                    count,
                    retry_after=retry_after,
                    default_delay=default_delay,
                )
                if retry
                else 0.0
            ),
            retry_after=retry_after,
        )
        self.last_decision = decision
        return decision

    def as_dict(self) -> dict[str, int]:
        return {category.value: int(self.counts.get(category.value, 0)) for category in FailureCategory}


@dataclass
class GlobalControlSnapshot:
    requested_limit: int
    active_limit: int
    minimum_active_limit: int
    cooldown_remaining: float
    rate_limit_events: int
    auth_failures: int
    scale_downs: int
    scale_ups: int
    circuit_open_reason: str | None
    cooldown_requested_seconds: float


class GlobalRuntimeController:
    """Coordinator-owned cooldown, circuit breaker and adaptive concurrency state."""

    def __init__(
        self,
        *,
        requested_limit: int,
        cooldown_seconds: float = 180.0,
        auth_failures_before_abort: int = 2,
        rate_limit_failures_before_abort: int = 6,
        rate_limit_window_seconds: float = 300.0,
        adaptive_enabled: bool = False,
        adaptive_scale_down_threshold: int = 2,
        adaptive_recovery_seconds: float = 900.0,
        clock: Callable[[], float],
    ) -> None:
        self.requested_limit = max(1, int(requested_limit))
        self.active_limit = self.requested_limit
        self.minimum_active_limit = self.active_limit
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.auth_failures_before_abort = max(1, int(auth_failures_before_abort))
        self.rate_limit_failures_before_abort = max(0, int(rate_limit_failures_before_abort))
        self.rate_limit_window_seconds = max(1.0, float(rate_limit_window_seconds))
        self.adaptive_enabled = bool(adaptive_enabled)
        self.adaptive_scale_down_threshold = max(1, int(adaptive_scale_down_threshold))
        self.adaptive_recovery_seconds = max(0.1, float(adaptive_recovery_seconds))
        self.clock = clock
        self.cooldown_until = 0.0
        self.cooldown_requested_seconds = 0.0
        self.rate_events: deque[float] = deque()
        self.adaptive_rate_events: deque[float] = deque()
        self.rate_incidents: dict[str, float] = {}
        self.rate_limit_event_count = 0
        self.auth_failures = 0
        self.scale_downs = 0
        self.scale_ups = 0
        self.circuit_open_reason: str | None = None
        self.last_rate_limit_at: float | None = None
        self.last_scale_at = self.clock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.rate_limit_window_seconds
        while self.rate_events and self.rate_events[0] < cutoff:
            self.rate_events.popleft()
        while self.adaptive_rate_events and self.adaptive_rate_events[0] < cutoff:
            self.adaptive_rate_events.popleft()
        self.rate_incidents = {
            key: seen_at
            for key, seen_at in self.rate_incidents.items()
            if seen_at >= cutoff
        }

    def request_cooldown(
        self,
        *,
        retry_after: float | None = None,
        incident_key: str | None = None,
    ) -> bool:
        """Request/extend a cooldown and return whether this is a new incident.

        A worker can report the same rate limit once per internal retry.  Those
        reports should extend the account-wide cooldown, but must not inflate
        adaptive-concurrency or circuit-breaker counters as separate incidents.
        """
        now = self.clock()
        self._prune(now)
        duration = self.cooldown_seconds
        # An explicit zero disables coordinator cooldown even when a provider
        # supplies Retry-After. This keeps the CLI flag authoritative.
        if duration > 0 and retry_after is not None:
            duration = max(duration, max(0.0, float(retry_after)))
        previous_until = max(self.cooldown_until, now)
        self.cooldown_until = max(self.cooldown_until, now + duration)
        self.cooldown_requested_seconds += max(0.0, self.cooldown_until - previous_until)
        normalized_key = str(incident_key).strip() if incident_key is not None else ""
        is_new_incident = not normalized_key or normalized_key not in self.rate_incidents
        if normalized_key:
            self.rate_incidents[normalized_key] = now
        self.last_rate_limit_at = now
        if not is_new_incident:
            return False
        self.rate_events.append(now)
        self.adaptive_rate_events.append(now)
        self.rate_limit_event_count += 1
        if (
            self.adaptive_enabled
            and len(self.adaptive_rate_events) >= self.adaptive_scale_down_threshold
            and self.active_limit > 1
        ):
            self.active_limit -= 1
            self.minimum_active_limit = min(self.minimum_active_limit, self.active_limit)
            self.scale_downs += 1
            self.last_scale_at = now
            # A fresh threshold window is required for another scale-down.
            self.adaptive_rate_events.clear()
            self.adaptive_rate_events.append(now)
        if (
            self.rate_limit_failures_before_abort > 0
            and len(self.rate_events) >= self.rate_limit_failures_before_abort
        ):
            self.circuit_open_reason = (
                "global rate-limit circuit opened after "
                f"{len(self.rate_events)} events within "
                f"{self.rate_limit_window_seconds:g}s"
            )
        return True

    def record_auth_failure(self) -> None:
        self.auth_failures += 1
        if self.auth_failures >= self.auth_failures_before_abort:
            self.circuit_open_reason = (
                "authentication circuit opened after "
                f"{self.auth_failures} failures"
            )

    def tick(self) -> None:
        now = self.clock()
        self._prune(now)
        if (
            self.adaptive_enabled
            and self.circuit_open_reason is None
            and self.active_limit < self.requested_limit
            and self.last_rate_limit_at is not None
            and now - self.last_rate_limit_at >= self.adaptive_recovery_seconds
            and now - self.last_scale_at >= self.adaptive_recovery_seconds
        ):
            self.active_limit += 1
            self.scale_ups += 1
            self.last_scale_at = now

    @property
    def cooldown_active(self) -> bool:
        return self.clock() < self.cooldown_until

    @property
    def dispatch_allowed(self) -> bool:
        return self.circuit_open_reason is None and not self.cooldown_active

    def snapshot(self) -> GlobalControlSnapshot:
        now = self.clock()
        return GlobalControlSnapshot(
            requested_limit=self.requested_limit,
            active_limit=self.active_limit,
            minimum_active_limit=self.minimum_active_limit,
            cooldown_remaining=max(0.0, self.cooldown_until - now),
            rate_limit_events=self.rate_limit_event_count,
            auth_failures=self.auth_failures,
            scale_downs=self.scale_downs,
            scale_ups=self.scale_ups,
            circuit_open_reason=self.circuit_open_reason,
            cooldown_requested_seconds=self.cooldown_requested_seconds,
        )
