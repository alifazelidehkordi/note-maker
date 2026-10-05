from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from . import selenium_legacy
from .downloads import score_download_trigger
from .errors import RateLimitError
from .models import ResponseWaitRequest
from .patchright_provider import PatchrightBrowserSession

_HARDENING_FLAG = "_p0_runtime_hardening_installed"
_ORIGINAL_SEND_MESSAGE = PatchrightBrowserSession.send_message
_ORIGINAL_WAIT_FOR_RESPONSE = PatchrightBrowserSession.wait_for_response


@contextmanager
def _strict_rate_limit_acknowledgement(
    session: PatchrightBrowserSession,
    operation: str,
) -> Iterator[None]:
    """Turn an undismissable rate-limit dialog into a typed retry signal."""

    original_dismiss = session._dismiss_rate_limit_modal

    def strict_dismiss() -> bool:
        dismissed = bool(original_dismiss())
        if not dismissed and session._rate_limit_visible():
            raise RateLimitError(
                f"ChatGPT rate-limit dialog remained visible during {operation}.",
                retry_after=getattr(
                    __import__(
                        "browser_runtime.patchright_provider",
                        fromlist=["RATE_LIMIT_WAIT_SECONDS"],
                    ),
                    "RATE_LIMIT_WAIT_SECONDS",
                    180,
                ),
            )
        return dismissed

    session._dismiss_rate_limit_modal = strict_dismiss  # type: ignore[method-assign]
    try:
        yield
    finally:
        session.__dict__.pop("_dismiss_rate_limit_modal", None)


def _hardened_send_message(self: PatchrightBrowserSession, text: str) -> None:
    with _strict_rate_limit_acknowledgement(self, "send"):
        _ORIGINAL_SEND_MESSAGE(self, text)


def _hardened_wait_for_response(
    self: PatchrightBrowserSession,
    request: ResponseWaitRequest,
) -> None:
    with _strict_rate_limit_acknowledgement(self, "response wait"):
        _ORIGINAL_WAIT_FOR_RESPONSE(self, request)


def _legacy_artifact_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
    expected_extensions=None,
) -> bool:
    expected = selenium_legacy.normalize_expected_extensions(expected_extensions)
    return bool(
        score_download_trigger(
            text=text,
            href=href,
            title=title,
            aria=aria,
            context=context,
            expected_extensions=expected,
        )
    )


def _legacy_opml_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
) -> bool:
    return _legacy_artifact_download_trigger(
        text=text,
        href=href,
        title=title,
        aria=aria,
        context=context,
        expected_extensions={".opml"},
    )


def install_runtime_hardening() -> None:
    """Install P0 fixes before providers and legacy facades capture callables."""

    if getattr(PatchrightBrowserSession, _HARDENING_FLAG, False):
        return
    PatchrightBrowserSession.send_message = _hardened_send_message  # type: ignore[method-assign]
    PatchrightBrowserSession.wait_for_response = _hardened_wait_for_response  # type: ignore[method-assign]
    setattr(PatchrightBrowserSession, _HARDENING_FLAG, True)

    # The legacy facade snapshots these functions during import. Replacing them
    # here keeps Selenium and Patchright on the same strict trigger policy.
    selenium_legacy.is_artifact_download_trigger = _legacy_artifact_download_trigger
    selenium_legacy.is_opml_download_trigger = _legacy_opml_download_trigger
