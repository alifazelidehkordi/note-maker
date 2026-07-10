from __future__ import annotations

from .contracts import BrowserProvider, BrowserSession
from .errors import BrowserConfigurationError
from .patchright_provider import PatchrightBrowserSession, PatchrightProvider
from .selenium_provider import SeleniumBrowserSession, SeleniumProvider


def create_browser_provider(name: str = 'selenium') -> BrowserProvider:
    normalized = str(name).strip().lower()
    if normalized == 'selenium':
        return SeleniumProvider()
    if normalized == 'patchright':
        return PatchrightProvider()
    raise BrowserConfigurationError(f"Unknown browser provider: {name!r}")


def ensure_browser_session(
    value: object,
    *,
    provider: BrowserProvider | None = None,
) -> BrowserSession:
    if isinstance(value, (SeleniumBrowserSession, PatchrightBrowserSession)):
        return value
    # Structural protocol checks can execute properties on arbitrary Selenium
    # objects, so use an explicit marker before falling back to wrapping.
    if getattr(value, 'provider_name', None) and hasattr(value, 'resolve_download'):
        return value  # type: ignore[return-value]
    selected = provider or create_browser_provider('selenium')
    return selected.wrap_handle(value)
