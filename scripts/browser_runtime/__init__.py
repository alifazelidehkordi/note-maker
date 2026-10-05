from .contracts import BrowserProvider, BrowserSession
from .errors import (
    ActiveProfileError,
    AuthenticationRequiredError,
    BrowserAuthenticationError,
    BrowserConfigurationError,
    BrowserCrashedError,
    BrowserDownloadError,
    BrowserNavigationError,
    BrowserResponseTimeout,
    BrowserRuntimeError,
    BrowserSendError,
    BrowserStartupError,
    BrowserUploadError,
    CloudflareChallengeError,
    DownloadNotFoundError,
    GenerationStalledError,
    NetworkUnavailableError,
    PageStateError,
    ProfileConfigurationError,
    ProfileLeaseError,
    ProfileRuntimeError,
    ProfileSnapshotError,
    RateLimitError,
    ResponseTimeoutError,
    SendError,
    TemporaryChatError,
    UnsupportedBrowserCapability,
    UploadError,
)
from .models import (
    BrowserHealth,
    BrowserHealthStatus,
    BrowserLaunchOptions,
    BrowserOperationRecord,
    DownloadRequest,
    DownloadSnapshot,
    ResponseWaitRequest,
    UploadRequest,
)
from .patchright_provider import PatchrightBrowserSession, PatchrightProvider
from .profile_safety import install_profile_safety
from .runtime_hardening import install_runtime_hardening

# Apply behavior fixes before factory/provider/session users snapshot affected callables.
install_runtime_hardening()
install_profile_safety()

from .profile_recovery_guard import install_profile_recovery_guard

install_profile_recovery_guard()

from .factory import create_browser_provider, ensure_browser_session
from .profile_manager import (
    AuthSessionEvidence,
    CleanupOutcome,
    CleanupStatus,
    OwnershipState,
    ProfileActivity,
    ProfileLease,
    ProfileManager,
    ProfileSnapshot,
    RetentionPolicy,
    RunProfileContext,
    WorkerProfileContext,
)
from .selenium_provider import SeleniumBrowserSession, SeleniumProvider
from .session_manager import ManagedBrowserSession, SessionBootstrapper
from .state_machine import ResponseState, ResponseStateMachine, SessionState

__all__ = [
    'BrowserProvider',
    'BrowserSession',
    'BrowserRuntimeError',
    'BrowserConfigurationError',
    'BrowserStartupError',
    'BrowserAuthenticationError',
    'AuthenticationRequiredError',
    'CloudflareChallengeError',
    'BrowserNavigationError',
    'NetworkUnavailableError',
    'PageStateError',
    'ProfileRuntimeError',
    'ProfileConfigurationError',
    'ProfileSnapshotError',
    'ActiveProfileError',
    'ProfileLeaseError',
    'BrowserUploadError',
    'UploadError',
    'BrowserSendError',
    'SendError',
    'RateLimitError',
    'BrowserResponseTimeout',
    'ResponseTimeoutError',
    'GenerationStalledError',
    'BrowserDownloadError',
    'DownloadNotFoundError',
    'BrowserCrashedError',
    'TemporaryChatError',
    'UnsupportedBrowserCapability',
    'BrowserHealth',
    'BrowserHealthStatus',
    'BrowserLaunchOptions',
    'BrowserOperationRecord',
    'DownloadSnapshot',
    'UploadRequest',
    'ResponseWaitRequest',
    'DownloadRequest',
    'SeleniumProvider',
    'SeleniumBrowserSession',
    'PatchrightProvider',
    'PatchrightBrowserSession',
    'AuthSessionEvidence',
    'CleanupOutcome',
    'CleanupStatus',
    'OwnershipState',
    'ProfileActivity',
    'ProfileLease',
    'ProfileManager',
    'ProfileSnapshot',
    'RetentionPolicy',
    'RunProfileContext',
    'WorkerProfileContext',
    'ManagedBrowserSession',
    'SessionBootstrapper',
    'SessionState',
    'ResponseState',
    'ResponseStateMachine',
    'create_browser_provider',
    'ensure_browser_session',
]
