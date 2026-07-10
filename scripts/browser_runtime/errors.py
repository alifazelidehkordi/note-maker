from __future__ import annotations


class BrowserRuntimeError(RuntimeError):
    """Base class for typed browser-runtime failures."""


class BrowserConfigurationError(BrowserRuntimeError):
    """The requested browser runtime configuration is invalid or unsupported."""


class BrowserStartupError(BrowserRuntimeError):
    """The browser process or persistent session could not be started."""


class BrowserAuthenticationError(BrowserRuntimeError):
    """The browser session is not authenticated or login could not complete."""


class AuthenticationRequiredError(BrowserAuthenticationError):
    """A visible browser login is required before automation can continue."""


class CloudflareChallengeError(BrowserAuthenticationError):
    """A Cloudflare or equivalent human-verification challenge remained active."""


class BrowserNavigationError(BrowserRuntimeError):
    """Navigation or page readiness failed."""


class NetworkUnavailableError(BrowserNavigationError):
    """The target could not be reached after bounded network recovery attempts."""


class PageStateError(BrowserNavigationError):
    """The page is reachable but not in the state required by the operation."""


class BrowserUploadError(BrowserRuntimeError):
    """An input artifact could not be uploaded completely."""


class UploadError(BrowserUploadError):
    """Provider-neutral upload failure alias used by runtime policies."""


class BrowserSendError(BrowserRuntimeError):
    """A prompt could not be submitted safely."""


class SendError(BrowserSendError):
    """Provider-neutral send failure alias used by runtime policies."""


class RateLimitError(BrowserSendError):
    """The service rejected or delayed work because of a rate limit."""

    def __init__(self, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BrowserResponseTimeout(BrowserRuntimeError, TimeoutError):
    """The assistant response did not become idle before the timeout."""


class ResponseTimeoutError(BrowserResponseTimeout):
    """Provider-neutral response timeout alias used by runtime policies."""


class GenerationStalledError(BrowserResponseTimeout):
    """Generation remained active beyond the configured stop-and-grace policy."""


class BrowserDownloadError(BrowserRuntimeError):
    """A downloadable artifact could not be resolved."""


class DownloadNotFoundError(BrowserDownloadError):
    """No fresh artifact matching the job contract could be found."""


class BrowserCrashedError(BrowserRuntimeError):
    """The underlying browser process or connection is no longer usable."""


class TemporaryChatError(PageStateError):
    """The temporary chat UI is unavailable or failed to initialize."""


class UnsupportedBrowserCapability(BrowserRuntimeError):
    """The selected provider does not implement a required capability."""

class ProfileRuntimeError(BrowserRuntimeError):
    """Base class for profile snapshot, ownership and lifecycle failures."""


class ProfileConfigurationError(ProfileRuntimeError):
    """Profile runtime paths or policies are invalid."""


class ProfileSnapshotError(ProfileRuntimeError):
    """A reference session could not be snapshotted or restored safely."""


class ActiveProfileError(ProfileRuntimeError):
    """A browser profile appears to be in use and cannot be copied or deleted."""


class ProfileLeaseError(ProfileRuntimeError):
    """Exclusive ownership of a browser profile could not be acquired."""

