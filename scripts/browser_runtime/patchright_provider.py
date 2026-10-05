from __future__ import annotations

import hashlib
import importlib
import os
import re
import shutil
import time
import urllib.request
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .contracts import BrowserSession
from .downloads import (
    is_expected_artifact,
    safe_path_component,
    salvage_download,
    score_download_trigger,
    snapshot_directory,
)
from .errors import (
    AuthenticationRequiredError,
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
    GenerationStalledError,
    NetworkUnavailableError,
    PageStateError,
    RateLimitError,
    TemporaryChatError,
    UnsupportedBrowserCapability,
)
from .models import (
    BrowserHealth,
    BrowserHealthStatus,
    BrowserLaunchOptions,
    DownloadRequest,
    ResponseWaitRequest,
    UploadRequest,
)
from .selectors import (
    ASSISTANT_MESSAGE_SELECTOR,
    ATTACH_BUTTON_SELECTORS,
    ATTACH_MENU_LABEL_PATTERNS,
    CHATGPT_URL,
    CLOUDFLARE_PHRASES,
    COOKIE_BUTTON_LABELS,
    DOWNLOAD_CANDIDATE_SELECTOR,
    EDITOR_SELECTORS,
    FILE_INPUT_SELECTOR,
    LOGIN_BUTTON_PATTERN,
    MODEL_BUTTON_SELECTORS,
    NETWORK_ERROR_MARKERS,
    RATE_LIMIT_MODAL_SELECTOR,
    RATE_LIMIT_PHRASES,
    SEND_BUTTON_SELECTORS,
    STOP_BUTTON_SELECTORS,
    UPLOAD_ERROR_SELECTORS,
    UPLOAD_PROGRESS_SELECTORS,
)
from .state_machine import (
    ResponseObservation,
    ResponseState,
    ResponseStateMachine,
    SessionState,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_DIR = ROOT / "patchright_profile"
DEFAULT_DOWNLOAD_DIR = ROOT / "downloads"
LONG_GENERATION_STOP_SECONDS = int(os.environ.get("LONG_GENERATION_STOP_SECONDS", "900"))
POST_STOP_GRACE_SECONDS = int(os.environ.get("POST_STOP_GRACE_SECONDS", "60"))
RATE_LIMIT_WAIT_SECONDS = int(os.environ.get("RATE_LIMIT_WAIT_SECONDS", "180"))
# Cooldown used when a rate-limit modal survives the bounded re-check during a
# response wait or blocks a download (see _await_response / download paths).
RATE_LIMIT_RECHECK_RETRY_SECONDS = RATE_LIMIT_WAIT_SECONDS
# Verify-and-set ChatGPT "thinking effort" before every submission (plan item 4).
# Fail closed: a batch silently generated at Medium when High was required is
# worse than an abort. ArrowRight steps per current level over the 3-level slider.
CHATGPT_REQUIRED_EFFORT = os.environ.get("CHATGPT_REQUIRED_EFFORT", "").strip().lower()
EFFORT_SLIDER_STEPS = {"low": 2, "medium": 1, "high": 0}
# Inline Markdown source delivery (plan item 5): bypass the upload path by
# appending the full source text to the prompt. The prompt hash is computed on
# the ORIGINAL prompt only, so toggling inline mode never invalidates resume.
INLINE_MARKDOWN_ENABLED = os.environ.get("NOTE_MAKER_INLINE_MARKDOWN", "0") == "1"
INLINE_MARKDOWN_MAX_CHARS = int(os.environ.get("NOTE_MAKER_INLINE_MAX_CHARS", "50000"))


def _load_patchright():
    try:
        sync_api = importlib.import_module("patchright.sync_api")
    except ModuleNotFoundError as exc:
        raise BrowserConfigurationError(
            "Patchright is not installed. Run setup.sh/setup.cmd or install "
            "patchright==1.61.2 and then run 'patchright install chromium'."
        ) from exc
    return sync_api


def _log(message: str) -> None:
    print(message, flush=True)
    log_path = Path(os.environ.get("CHATGPT_RUN_LOG", ROOT / "run.log"))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _message(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


def is_network_error(exc: BaseException) -> bool:
    lowered = _message(exc).lower()
    return any(marker in lowered for marker in NETWORK_ERROR_MARKERS)


def translate_patchright_error(operation: str, exc: BaseException) -> BrowserRuntimeError:
    if isinstance(exc, BrowserRuntimeError):
        return exc
    message = _message(exc)
    lowered = message.lower()
    if operation == "start" and any(
        marker in lowered
        for marker in (
            "crashpad",
            "setsockopt: operation not permitted",
            "signal=sigtrap",
            "no usable sandbox",
            "failed to move to new namespace",
        )
    ):
        return BrowserConfigurationError(
            "Browser launch is blocked by the host sandbox/security policy. "
            "Run the browser workflow with permission to launch Chromium. "
            f"Original startup error: {message}"
        )
    if any(
        marker in lowered
        for marker in (
            "target page, context or browser has been closed",
            "browser has been closed",
            "page crashed",
            "connection closed",
            "browser closed",
        )
    ):
        error_type = BrowserCrashedError
    elif is_network_error(exc):
        error_type = NetworkUnavailableError
    elif "cloudflare" in lowered or "verify you are human" in lowered:
        error_type = CloudflareChallengeError
    elif "login required" in lowered or "authentication required" in lowered:
        error_type = AuthenticationRequiredError
    elif "rate limit" in lowered or "too many requests" in lowered:
        return RateLimitError(f"{operation} failed: {message}")
    elif operation == "start":
        error_type = BrowserStartupError
    elif operation == "authenticate":
        error_type = AuthenticationRequiredError
    elif operation in {"navigate", "new_chat", "select_model", "recover"}:
        error_type = BrowserNavigationError
    elif operation == "upload":
        error_type = BrowserUploadError
    elif operation == "send":
        error_type = BrowserSendError
    elif operation == "wait_response":
        error_type = BrowserResponseTimeout
    elif operation == "download":
        error_type = BrowserDownloadError
    else:
        error_type = BrowserRuntimeError
    return error_type(f"{operation} failed: {message}")




def _system_chromium_path() -> str | None:
    override = os.environ.get("CHATGPT_CHROME_BINARY", "").strip()
    if override:
        return override
    for name in (
        "google-chrome-stable",
        "google-chrome",
        "chromium-browser",
        "chromium",
        "microsoft-edge-stable",
        "msedge",
    ):
        found = shutil.which(name)
        if found:
            return found
    return None

def _network_available(timeout: int = 5) -> bool:
    try:
        with urllib.request.urlopen("https://chatgpt.com", timeout=timeout):
            return True
    except Exception:
        return False


def _wait_for_network(timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _network_available(timeout=min(5, max(1, int(deadline - time.monotonic())))):
            return True
        time.sleep(2)
    return False


def _locator_visible(locator: Any, timeout_ms: int = 300) -> bool:
    try:
        return bool(locator.is_visible(timeout=timeout_ms))
    except TypeError:
        try:
            return bool(locator.is_visible())
        except Exception:
            return False
    except Exception:
        return False


def _locator_enabled(locator: Any) -> bool:
    try:
        return bool(locator.is_enabled())
    except Exception:
        return False


def _first_visible(page: Any, selectors: Iterable[str], timeout_ms: int = 300) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if _locator_visible(locator, timeout_ms=timeout_ms):
                return locator
        except Exception:
            continue
    return None


def _body_text(page: Any, timeout_ms: int = 2000) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=timeout_ms))
    except TypeError:
        try:
            return str(page.locator("body").inner_text())
        except Exception:
            return ""
    except Exception:
        return ""


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def _apply_stealth(context: Any) -> None:
    try:
        module = importlib.import_module("playwright_stealth")
        stealth_type = module.Stealth
        stealth = stealth_type(init_scripts_only=True)
        stealth.apply_stealth_sync(context)
    except ModuleNotFoundError as exc:
        raise BrowserConfigurationError(
            "playwright-stealth is not installed. Run setup.sh/setup.cmd."
        ) from exc
    except Exception as exc:
        # Patchright already carries anti-detection patches. Stealth is an
        # additional layer and must not make the provider unusable.
        _log(f"Patchright stealth warning: {exc}")


class PatchrightBrowserSession:
    provider_name = "patchright"

    def __init__(
        self,
        *,
        playwright: Any,
        context: Any,
        page: Any,
        options: BrowserLaunchOptions,
        profile_dir: Path,
        download_dir: Path,
    ) -> None:
        self._playwright = playwright
        self._context = context
        self._page = page
        self._crashed = False
        self._options = options
        self._profile_dir = profile_dir
        self._download_dir = download_dir
        self._closed = False
        self._state = SessionState.CREATED
        self._last_send_hash: str | None = None
        self._last_send_assistant_count: int | None = None
        self._last_send_completed = False
        self._last_send_started_at: float | None = None
        self._inline_source_text = ""
        self._delivery_mode = "upload"
        self._download_fallbacks = 0
        self._last_fallback_reason: str | None = None
        self._bind_page(page)

    def _bind_page(self, page: Any) -> None:
        self._page = page
        self._crashed = False
        try:
            page.on("crash", self._on_page_crash)
        except Exception:
            pass

    def _on_page_crash(self, *_args: object) -> None:
        self._crashed = True
        self._set_state(SessionState.FAILED)

    def _translate_failure(self, operation: str, exc: BaseException) -> BrowserRuntimeError:
        translated = translate_patchright_error(operation, exc)
        if isinstance(translated, BrowserCrashedError):
            self._on_page_crash()
        return translated

    @property
    def raw_handle(self) -> object:
        return self._page

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def profile_dir(self) -> Path:
        return self._profile_dir

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    def _set_state(self, state: SessionState) -> None:
        self._state = state

    def _guard(self, operation: str, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            self._state = SessionState.FAILED
            raise self._translate_failure(operation, exc) from exc

    def is_alive(self) -> bool:
        if self._closed or self._crashed:
            return False
        try:
            if hasattr(self._page, "is_closed") and self._page.is_closed():
                return False
            _ = self._page.url
            return True
        except Exception:
            return False

    def health(self) -> BrowserHealth:
        if not self.is_alive():
            return BrowserHealth(BrowserHealthStatus.DEAD, "Patchright page is closed or unreachable.")
        try:
            current_url = str(self._page.url or "") or None
            body = _body_text(self._page, timeout_ms=500)
            if _contains_any(body, CLOUDFLARE_PHRASES):
                return BrowserHealth(
                    BrowserHealthStatus.DEGRADED,
                    "Cloudflare challenge is visible.",
                    current_url,
                )
            return BrowserHealth(BrowserHealthStatus.HEALTHY, current_url=current_url)
        except Exception as exc:
            return BrowserHealth(BrowserHealthStatus.DEGRADED, _message(exc))

    def recover(self, reason: str = "") -> bool:
        self._set_state(SessionState.RECOVERING)
        try:
            if not self.is_alive():
                try:
                    self._bind_page(self._context.new_page())
                except Exception:
                    return False
            target = str(getattr(self._page, "url", "") or self._options.url or CHATGPT_URL)
            self._navigate_with_retry(target, attempts=2)
            self._wait_for_editor(timeout=min(60, self._options.navigation_timeout))
            self._set_state(SessionState.READY)
            return True
        except Exception as exc:
            _log(f"Patchright recovery failed ({reason or 'unspecified'}): {exc}")
            self._set_state(SessionState.FAILED)
            return False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._set_state(SessionState.CLOSED)
        try:
            self._context.close()
        except Exception:
            pass
        try:
            self._playwright.stop()
        except Exception:
            pass

    def set_window_size(self, width: int, height: int) -> None:
        try:
            self._page.set_viewport_size({"width": width, "height": height})
        except Exception:
            try:
                self._page.evaluate(f"window.resizeTo({int(width)}, {int(height)})")
            except Exception:
                pass

    def _navigate_with_retry(self, url: str, *, attempts: int = 4) -> None:
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self._options.navigation_timeout * 1000,
                )
                return
            except Exception as exc:
                last_error = exc
                if is_network_error(exc) and attempt < attempts:
                    _log(f"Patchright network error ({attempt}/{attempts}): {exc}")
                    if not _wait_for_network(self._options.network_recovery_timeout):
                        raise NetworkUnavailableError(
                            "Network did not recover before the configured deadline."
                        ) from exc
                    time.sleep(min(2 * attempt, 6))
                    continue
                if attempt < attempts:
                    time.sleep(min(attempt, 3))
                    continue
                raise
        if last_error is not None:
            raise last_error

    def navigate(self, url: str) -> None:
        self._set_state(SessionState.STARTING)
        self._guard("navigate", self._navigate_with_retry, url)
        self._set_state(SessionState.AUTH_CHECK)

    def _dismiss_cookie_banner(self) -> None:
        for label in COOKIE_BUTTON_LABELS:
            try:
                button = self._page.get_by_role("button", name=label).first
                if _locator_visible(button):
                    button.click()
                    time.sleep(0.3)
                    return
            except Exception:
                continue

    def _cloudflare_visible(self) -> bool:
        return _contains_any(_body_text(self._page), CLOUDFLARE_PHRASES)

    def _visible_rate_limit_dialog(self):
        selectors = (
            RATE_LIMIT_MODAL_SELECTOR,
            "[role='dialog']",
            "[data-testid*='rate-limit' i]",
            "[data-radix-portal] [role='dialog']",
        )
        for selector in selectors:
            try:
                dialogs = self._page.locator(selector)
                for index in range(int(dialogs.count()) - 1, -1, -1):
                    dialog = dialogs.nth(index)
                    if not _locator_visible(dialog):
                        continue
                    text = str(dialog.inner_text(timeout=1000) or "")
                    if _contains_any(text, RATE_LIMIT_PHRASES):
                        return dialog
            except Exception:
                continue
        return None

    def _rate_limit_visible(self) -> bool:
        if self._visible_rate_limit_dialog() is not None:
            return True
        return _contains_any(_body_text(self._page), RATE_LIMIT_PHRASES)

    def _login_buttons_visible(self) -> bool:
        try:
            pattern = re.compile(LOGIN_BUTTON_PATTERN, re.I)
            for role in ("button", "link"):
                control = self._page.get_by_role(role, name=pattern).first
                if _locator_visible(control):
                    return True
            explicit = self._page.locator(
                "a[href*='/auth/login'], a[href*='auth0'], "
                "[data-testid*='login' i], [data-testid*='log-in' i]"
            ).first
            return _locator_visible(explicit)
        except Exception:
            return False

    def _find_editor(self, *, timeout: int) -> Any:
        deadline = time.monotonic() + timeout
        last_error: BaseException | None = None
        while time.monotonic() < deadline:
            for selector in EDITOR_SELECTORS:
                try:
                    editor = self._page.locator(selector).first
                    editor.wait_for(state="visible", timeout=min(5000, max(500, int((deadline - time.monotonic()) * 1000))))
                    if _locator_enabled(editor):
                        return editor
                except Exception as exc:
                    last_error = exc
            time.sleep(0.5)
        raise PageStateError(f"ChatGPT prompt editor was not ready: {last_error}")

    def _wait_for_editor(self, *, timeout: int) -> None:
        self._find_editor(timeout=timeout)

    def wait_until_logged_in(self, timeout: int = 600) -> None:
        self._set_state(SessionState.AUTH_CHECK)
        deadline = time.monotonic() + timeout
        challenge_seen = False
        while time.monotonic() < deadline:
            self._dismiss_cookie_banner()
            if self._cloudflare_visible():
                challenge_seen = True
                if self._options.headless:
                    raise CloudflareChallengeError(
                        "Cloudflare verification is visible in headless mode. Re-run headful."
                    )
                _log("Cloudflare verification is visible; complete it in the browser window.")
                time.sleep(2)
                continue
            if self._login_buttons_visible():
                self._set_state(SessionState.AUTH_REQUIRED)
                if self._options.headless:
                    raise AuthenticationRequiredError(
                        "Login required in headless mode. Run Patchright headful once with the same profile."
                    )
                _log("Waiting for ChatGPT login in the persistent Patchright profile...")
                time.sleep(2)
                continue
            try:
                self._wait_for_editor(timeout=min(10, max(1, int(deadline - time.monotonic()))))
                self._set_state(SessionState.READY)
                return
            except PageStateError:
                time.sleep(1)
        if challenge_seen:
            raise CloudflareChallengeError("Cloudflare challenge did not clear before login timeout.")
        raise AuthenticationRequiredError("Timed out waiting for an authenticated ChatGPT editor.")

    def start_new_chat(self) -> None:
        try:
            self._navigate_with_retry(CHATGPT_URL, attempts=3)
            self._wait_for_editor(timeout=self._options.navigation_timeout)
            if self._login_buttons_visible():
                raise AuthenticationRequiredError(
                    "ChatGPT opened an anonymous composer; the saved login session is not active."
                )
            self._last_send_hash = None
            self._last_send_assistant_count = None
            self._last_send_completed = False
            self._last_send_started_at = None
            self._inline_source_text = ""
            self._delivery_mode = "upload"
            self._set_state(SessionState.READY)
        except BrowserRuntimeError:
            raise
        except Exception as exc:
            translated = self._translate_failure("new_chat", exc)
            if isinstance(translated, (BrowserCrashedError, NetworkUnavailableError)):
                raise translated from exc
            raise TemporaryChatError(f"Could not open a fresh temporary chat: {_message(exc)}") from exc

    def select_model(self, model: str | None) -> None:
        if not model:
            return
        try:
            button = _first_visible(self._page, MODEL_BUTTON_SELECTORS, timeout_ms=800)
            if button is None:
                raise PageStateError("Model switcher button is not visible.")
            button.click()
            time.sleep(0.5)
            option = self._page.get_by_text(model, exact=False).first
            if not _locator_visible(option, timeout_ms=1500):
                raise PageStateError(f"Requested model option is not visible: {model}")
            option.click()
            time.sleep(0.5)
        except Exception as exc:
            raise self._translate_failure("select_model", exc) from exc

    def assistant_message_count(self) -> int:
        try:
            return int(self._page.locator(ASSISTANT_MESSAGE_SELECTOR).count())
        except Exception as exc:
            raise self._translate_failure("wait_response", exc) from exc

    def _upload_error_text(self) -> str:
        for selector in UPLOAD_ERROR_SELECTORS:
            try:
                locator = self._page.locator(selector).first
                if _locator_visible(locator):
                    text = str(locator.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def _upload_pending(self) -> bool:
        for selector in UPLOAD_PROGRESS_SELECTORS:
            try:
                if _locator_visible(self._page.locator(selector).first):
                    return True
            except Exception:
                continue
        return False

    def upload(self, request: UploadRequest) -> None:
        if not request.file_path.exists():
            raise BrowserUploadError(f"Upload source does not exist: {request.file_path}")
        self._inline_source_text = ""
        if (
            INLINE_MARKDOWN_ENABLED
            and request.file_path.suffix.lower() == ".md"
            and INLINE_MARKDOWN_MAX_CHARS > 0
        ):
            source = request.file_path.read_text(encoding="utf-8")
            if not source.strip():
                raise BrowserUploadError(f"Source Markdown is empty: {request.file_path.name}")
            if len(source) > INLINE_MARKDOWN_MAX_CHARS:
                # Too large for a single message; fall back to the upload path.
                _log(
                    "Source delivery: inline skipped, "
                    f"{request.file_path.name} exceeds NOTE_MAKER_INLINE_MAX_CHARS "
                    f"({len(source)} > {INLINE_MARKDOWN_MAX_CHARS}); uploading instead."
                )
            else:
                self._inline_source_text = (
                    f"\n\n--- BEGIN SOURCE DOCUMENT: {request.file_path.name} ---\n"
                    + source
                    + "\n--- END SOURCE DOCUMENT ---"
                )
                self._delivery_mode = "inline"
                _log(
                    "Source delivery: inline Markdown, "
                    f"{request.file_path.name}, {len(source)} characters (complete)."
                )
                self._set_state(SessionState.READY)
                return
        self._delivery_mode = "upload"
        self._set_state(SessionState.UPLOADING)
        try:
            def compatible_file_input():
                inputs = self._page.locator(FILE_INPUT_SELECTOR)
                try:
                    count = int(inputs.count())
                except Exception:
                    return None
                suffix = request.file_path.suffix.lower()
                fallback = None
                for index in range(count):
                    candidate = inputs.nth(index)
                    try:
                        accept = str(candidate.get_attribute("accept") or "").lower()
                    except Exception:
                        accept = ""
                    if not accept or "*/*" in accept:
                        fallback = fallback or candidate
                        continue
                    tokens = {token.strip() for token in accept.split(",")}
                    if suffix in tokens:
                        return candidate
                    # ChatGPT now keeps a separate image-only file input in
                    # the composer. Never feed Markdown/PDF documents to it.
                    IMAGE_ONLY_TOKENS = {
                        ".avif", ".bmp", ".gif", ".heic", ".heif",
                        ".png", ".jpg", ".jpeg", ".webp", ".mpo",
                    }
                    if all("image/" in token or token in IMAGE_ONLY_TOKENS for token in tokens):
                        # Photo-only control: feeding a document here produces
                        # "This file type isn't supported". Never a fallback.
                        continue
                    fallback = fallback or candidate
                return fallback

            file_input = compatible_file_input()
            attached_via_chooser = False
            if file_input is None:
                attach = _first_visible(self._page, ATTACH_BUTTON_SELECTORS, timeout_ms=800)
                if attach is None:
                    raise PageStateError("Attach button and file input are both unavailable.")
                try:
                    attach.evaluate("(element) => element.click()")
                except Exception:
                    attach.click()

                # The redesigned composer opens a two-step menu: the document
                # input is only created after selecting "Upload from computer"
                # / "Add photos & files". Setting one of the image-only inputs
                # already present in the DOM produces the misleading "This file
                # type isn't supported" error, so drive the menu explicitly.
                for pattern in ATTACH_MENU_LABEL_PATTERNS:
                    menu_item = self._page.get_by_text(re.compile(pattern, re.I)).first
                    try:
                        visible = _locator_visible(menu_item, timeout_ms=800)
                    except Exception:
                        visible = False
                    if not visible:
                        continue
                    try:
                        with self._page.expect_file_chooser(timeout=3000) as chooser_info:
                            menu_item.click()
                        chooser_info.value.set_files(str(request.file_path))
                        attached_via_chooser = True
                        break
                    except Exception:
                        # Older composer variants expose a document input after
                        # the menu opens without emitting a file-chooser event;
                        # fall through to the polling path below.
                        break

                deadline = time.monotonic() + 3
                while (
                    not attached_via_chooser
                    and file_input is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.25)
                    file_input = compatible_file_input()
            if file_input is None and not attached_via_chooser:
                raise PageStateError("A document-compatible file input is unavailable.")
            if not attached_via_chooser:
                file_input.set_input_files(str(request.file_path))

            deadline = time.monotonic() + request.timeout
            name_marker = request.file_path.name[:48]
            seen_name = False
            stable_since: float | None = None
            while time.monotonic() < deadline:
                error_text = self._upload_error_text()
                if error_text:
                    raise BrowserUploadError(f"ChatGPT reported upload failure: {error_text}")
                body = _body_text(self._page)
                if name_marker in body:
                    seen_name = True
                pending = self._upload_pending()
                if seen_name and not pending:
                    stable_since = stable_since or time.monotonic()
                    if time.monotonic() - stable_since >= 1.0:
                        self._set_state(SessionState.READY)
                        return
                else:
                    stable_since = None
                time.sleep(0.5)
            raise BrowserUploadError(f"Timed out waiting for upload: {request.file_path.name}")
        except Exception as exc:
            self._set_state(SessionState.FAILED)
            raise self._translate_failure("upload", exc) from exc

    @staticmethod
    def _prompt_hash(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def _editor_text(self, editor: Any) -> str:
        for method_name in ("input_value", "inner_text", "text_content"):
            method = getattr(editor, method_name, None)
            if method is None:
                continue
            try:
                value = method()
                if value is not None:
                    return str(value).strip()
            except Exception:
                continue
        return ""

    def _fill_editor(self, editor: Any, text: str) -> None:
        try:
            editor.fill(text)
            return
        except Exception:
            pass
        editor.click()
        try:
            self._page.keyboard.press("Control+A")
            self._page.keyboard.press("Backspace")
        except Exception:
            pass
        self._page.keyboard.insert_text(text)

    def _verify_required_effort(self) -> None:
        """Verify (and if needed set) the required thinking effort before a
        submission. Fails closed on any mismatch after the adjustment attempt.

        The ArrowRight step count is computed from the reported current level
        via EFFORT_SLIDER_STEPS (low: 2, medium: 1, high: 0); an unknown level
        still attempts the slider and relies on the post-condition check.
        """
        if not CHATGPT_REQUIRED_EFFORT:
            return
        control = self._page.locator("button[data-selected-reasoning-effort]").first
        actual = str(control.get_attribute("data-selected-reasoning-effort") or "").lower()
        if actual != CHATGPT_REQUIRED_EFFORT:
            control.click()
            slider = self._page.locator("[data-reasoning-slider]").first
            if slider.count() and _locator_visible(slider):
                steps = EFFORT_SLIDER_STEPS.get(actual, EFFORT_SLIDER_STEPS["high"])
                for _ in range(max(steps, 1)):
                    slider.press("ArrowRight")
                try:
                    self._page.keyboard.press("Escape")
                except Exception:
                    pass
            actual = str(control.get_attribute("data-selected-reasoning-effort") or "").lower()
        if actual != CHATGPT_REQUIRED_EFFORT:
            raise BrowserConfigurationError(
                f"Thinking effort must be {CHATGPT_REQUIRED_EFFORT!r}; "
                f"composer reports {actual!r}. Submission blocked to avoid "
                "generating at the wrong effort."
            )
        _log(f"Verified thinking effort before submission: {actual}")

    def send_message(self, text: str) -> None:
        self._verify_required_effort()
        normalized = text.strip()
        if not normalized:
            raise BrowserSendError("Cannot send an empty prompt.")
        self._set_state(SessionState.SENDING)
        # Prompt hash MUST be computed on the original prompt, before any
        # inline source is appended (manifest/resume dedupe keys on it).
        prompt_hash = self._prompt_hash(normalized)
        before_count = self.assistant_message_count()

        # Idempotency guard: if a previous call for the same prompt already
        # produced a new assistant message, a retry must not click Send again.
        if prompt_hash == self._last_send_hash and self._last_send_assistant_count is not None:
            if before_count > self._last_send_assistant_count or self._generation_visible():
                self._last_send_completed = True
                self._set_state(SessionState.GENERATING)
                return
            if (
                not self._last_send_completed
                and self._last_send_started_at is not None
                and time.monotonic() - self._last_send_started_at < 60
            ):
                raise BrowserSendError(
                    "A send for the same prompt is still unconfirmed; duplicate click was blocked."
                )

        try:
            if self._rate_limit_visible():
                self._dismiss_rate_limit_modal()
                _log("Rate-limit modal acknowledged; continuing send without cooldown.")
            editor = self._find_editor(timeout=self._options.action_timeout)
            outgoing = normalized + getattr(self, "_inline_source_text", "")
            current = self._editor_text(editor)
            if current != outgoing:
                self._fill_editor(editor, outgoing)
            self._last_send_hash = prompt_hash
            self._last_send_assistant_count = before_count
            self._last_send_completed = False
            self._last_send_started_at = time.monotonic()

            button = _first_visible(self._page, SEND_BUTTON_SELECTORS, timeout_ms=1000)
            if button is not None and _locator_enabled(button):
                # ChatGPT's current composer can leave Playwright/Patchright's
                # pointer-style click unhandled even though the send button is
                # visible and enabled. Selenium already uses a DOM click for
                # this UI. Prefer the same path here, with the normal locator
                # click retained for test doubles and older browser builds.
                try:
                    button.evaluate("(element) => element.click()")
                except Exception:
                    button.click()
            else:
                self._page.keyboard.press("Enter")

            acknowledgement_started_at = time.monotonic()
            deadline = acknowledgement_started_at + 20
            keyboard_fallback_used = False
            while time.monotonic() < deadline:
                current_count = self.assistant_message_count()
                composer_text = self._editor_text(editor)
                if current_count > before_count or not composer_text:
                    self._last_send_completed = True
                    self._set_state(SessionState.GENERATING)
                    return
                if (
                    not keyboard_fallback_used
                    and time.monotonic() - acknowledgement_started_at >= 2
                    and not self._generation_visible()
                ):
                    # The current ChatGPT UI occasionally ignores synthetic
                    # pointer/DOM clicks under Patchright while leaving the
                    # prompt visibly untouched. Enter is the native composer
                    # submit shortcut, so use it only after proving the click
                    # did not clear the editor or start generation.
                    keyboard_fallback_used = True
                    try:
                        editor.press("Enter")
                    except Exception:
                        editor.click()
                        self._page.keyboard.press("Enter")
                if self._rate_limit_visible():
                    self._dismiss_rate_limit_modal()
                time.sleep(0.4)
            raise BrowserSendError(
                "Send acknowledgement was not observed; duplicate send was prevented."
            )
        except Exception as exc:
            self._set_state(SessionState.FAILED)
            raise self._translate_failure("send", exc) from exc

    def _generation_visible(self) -> bool:
        return _first_visible(self._page, STOP_BUTTON_SELECTORS, timeout_ms=250) is not None

    def _download_candidate_exists(self, expected_extensions: Iterable[str] = (".opml", ".md")) -> bool:
        return bool(self._find_download_candidates(expected_extensions, limit=1))

    def _dismiss_rate_limit_modal(self) -> bool:
        if not self._rate_limit_visible():
            return True

        dialog = self._visible_rate_limit_dialog()
        scope = dialog if dialog is not None else self._page
        label_pattern = re.compile(
            r"^\s*(got\s*it|ok(?:ay)?|باشه|متوجه شدم)\s*[.!]?\s*$",
            re.I,
        )
        candidates = []
        try:
            candidates.append(scope.get_by_role("button", name=label_pattern).first)
        except Exception:
            pass
        for selector in (
            "button:has-text('Got it')",
            "button:has-text('OK')",
            "[role='button']:has-text('Got it')",
            "[role='button']:has-text('باشه')",
        ):
            try:
                candidates.append(scope.locator(selector).first)
            except Exception:
                continue

        clicked = False
        for button in candidates:
            if not _locator_visible(button):
                continue
            # The current modal can sit behind an overlay that defeats a
            # pointer-style click. A DOM click is the most reliable first path.
            try:
                button.evaluate("(element) => element.click()")
                clicked = True
                break
            except Exception:
                try:
                    button.click(force=True, timeout=2000)
                    clicked = True
                    break
                except Exception:
                    try:
                        button.click(timeout=2000)
                        clicked = True
                        break
                    except Exception:
                        continue

        if not clicked:
            # Final DOM fallback avoids depending on changing test ids, portal
            # wrappers, or accessible-name computation in the live UI.
            try:
                clicked = bool(
                    self._page.evaluate(
                        """() => {
                            const accepted = new Set([
                                'got it', 'ok', 'okay', 'باشه', 'متوجه شدم'
                            ]);
                            const controls = document.querySelectorAll(
                                "button, [role='button']"
                            );
                            for (const control of controls) {
                                const text = (
                                    control.innerText ||
                                    control.textContent ||
                                    control.getAttribute('aria-label') ||
                                    ''
                                ).trim().toLowerCase().replace(/[.!]+$/, '');
                                if (accepted.has(text)) {
                                    control.click();
                                    return true;
                                }
                            }
                            return false;
                        }"""
                    )
                )
            except Exception:
                clicked = False

        if not clicked:
            _log("Rate-limit modal is visible, but its acknowledgement button was not found.")
            return False

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not self._rate_limit_visible():
                _log("Rate-limit modal dismissed successfully.")
                return True
            time.sleep(0.2)
        _log("Rate-limit acknowledgement was clicked, but the modal remained visible.")
        return False

    def dismiss_rate_limit_modal(self) -> bool:
        """Dismiss the live rate-limit acknowledgement without navigating."""
        if not self._rate_limit_visible():
            return False
        return self._dismiss_rate_limit_modal()

    def wait_for_response(self, request: ResponseWaitRequest) -> None:
        self._set_state(SessionState.GENERATING)
        machine = ResponseStateMachine(
            required_assistant_count=request.min_assistant_count,
            stable_seconds=5.0,
        )
        deadline = time.monotonic() + request.timeout
        extended = False
        # Bounded re-check for transient rate-limit modals (plan item 3,
        # critic-pinned semantics): the counter counts consecutive
        # RATE_LIMITED observations WITHIN this _await_response call and
        # resets on ANY non-RATE_LIMITED observation. Only dismissal failure
        # or exhausting the bound raises; a successfully dismissed transient
        # modal just continues the wait.
        RATE_LIMIT_RECHECK_BOUND = 3
        consecutive_rate_limited = 0
        while time.monotonic() < deadline:
            now = time.monotonic()
            rate_limited = self._rate_limit_visible()
            state = machine.observe(
                ResponseObservation(
                    assistant_count=self.assistant_message_count(),
                    generating=self._generation_visible(),
                    body_text=_body_text(self._page),
                    has_download=self._download_candidate_exists(),
                    rate_limited=rate_limited,
                    now=now,
                )
            )

            if state is ResponseState.RATE_LIMITED:
                consecutive_rate_limited += 1
                dismissed = self._dismiss_rate_limit_modal()
                detail = (
                    "acknowledged"
                    if dismissed
                    else "remained visible after acknowledgement"
                )
                if not dismissed or consecutive_rate_limited >= RATE_LIMIT_RECHECK_BOUND:
                    raise RateLimitError(
                        f"ChatGPT response was blocked by a rate-limit dialog ({detail}).",
                        retry_after=RATE_LIMIT_RECHECK_RETRY_SECONDS,
                    )
                time.sleep(1)
                continue

            # Any non-RATE_LIMITED observation resets the bounded re-check.
            consecutive_rate_limited = 0

            if state in {ResponseState.DOWNLOAD_READY, ResponseState.STABLE}:
                self._last_send_completed = True
                self._set_state(SessionState.READY)
                return

            generation_since = machine.generation_since
            if generation_since is not None:
                elapsed = now - generation_since
                if not extended and now >= deadline - 5:
                    deadline += min(300, LONG_GENERATION_STOP_SECONDS)
                    extended = True
                if elapsed >= LONG_GENERATION_STOP_SECONDS:
                    stop = _first_visible(self._page, STOP_BUTTON_SELECTORS, timeout_ms=500)
                    if stop is not None:
                        try:
                            stop.click()
                        except Exception:
                            pass
                    grace_deadline = time.monotonic() + POST_STOP_GRACE_SECONDS
                    while time.monotonic() < grace_deadline:
                        if self._download_candidate_exists():
                            self._set_state(SessionState.READY)
                            return
                        if not self._generation_visible():
                            self._set_state(SessionState.READY)
                            return
                        time.sleep(1)
                    raise GenerationStalledError(
                        "Long generation was stopped but no stable response or artifact appeared."
                    )
            time.sleep(1)

        raise BrowserResponseTimeout("Timed out while waiting for ChatGPT response completion.")

    def snapshot_downloads(self):
        return snapshot_directory(self._download_dir)

    def _candidate_fields(self, element: Any) -> tuple[str, str, str, str]:
        def read(method_name: str, *args) -> str:
            method = getattr(element, method_name, None)
            if method is None:
                return ""
            try:
                return str(method(*args) or "").strip()
            except Exception:
                return ""

        return (
            read("inner_text"),
            read("get_attribute", "href"),
            read("get_attribute", "title"),
            read("get_attribute", "aria-label"),
        )

    def _find_download_candidates(
        self,
        expected_extensions: Iterable[str],
        *,
        limit: int | None = None,
    ) -> list[tuple[int, Any]]:
        try:
            assistants = self._page.locator(ASSISTANT_MESSAGE_SELECTOR)
            count = int(assistants.count())
        except Exception:
            return []
        ranked: list[tuple[int, Any]] = []
        for assistant_index in range(count - 1, -1, -1):
            assistant = assistants.nth(assistant_index)
            try:
                context = str(assistant.inner_text() or "")[:4000]
                elements = assistant.locator(DOWNLOAD_CANDIDATE_SELECTOR)
                element_count = int(elements.count())
            except Exception:
                continue
            for element_index in range(element_count - 1, -1, -1):
                element = elements.nth(element_index)
                if not _locator_visible(element):
                    continue
                text, href, title, aria = self._candidate_fields(element)
                score = score_download_trigger(
                    text=text,
                    href=href,
                    title=title,
                    aria=aria,
                    context=context,
                    expected_extensions=expected_extensions,
                )
                if score:
                    ranked.append((score, element))
            if ranked:
                break
        ranked.sort(key=lambda item: item[0], reverse=True)
        return ranked[:limit] if limit is not None else ranked

    def _staging_dir(self, request: DownloadRequest) -> Path:
        if request.destination_dir is not None:
            target = request.destination_dir
        else:
            key = request.job_key or f"job-{request.started_at_ns}"
            target = self._download_dir / safe_path_component(key)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _save_download_event(self, download: Any, request: DownloadRequest) -> Path:
        staging = self._staging_dir(request)
        suggested = safe_path_component(str(getattr(download, "suggested_filename", "") or "artifact"))
        path = staging / suggested
        if not path.suffix and len(request.expected_extensions) == 1:
            path = path.with_suffix(next(iter(request.expected_extensions)))
        counter = 1
        candidate = path
        while candidate.exists():
            candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
            counter += 1
        download.save_as(str(candidate))
        if not is_expected_artifact(candidate, request.expected_extensions):
            raise BrowserDownloadError(
                f"Downloaded file does not match expected extensions {sorted(request.expected_extensions)}: {candidate.name}"
            )
        return candidate.resolve()

    def _event_download(self, request: DownloadRequest) -> Path | None:
        candidates = self._find_download_candidates(request.expected_extensions)
        if not candidates:
            return None
        per_candidate_timeout = max(1000, min(5_000, request.timeout * 1000))
        for _score, element in candidates:
            before_pages = tuple(getattr(self._context, "pages", (self._page,)))
            _text, candidate_href, _title, _aria = self._candidate_fields(element)
            _log(f"Patchright activating download candidate href={candidate_href[:240]!r}")
            try:
                element.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                with self._page.expect_download(timeout=per_candidate_timeout) as pending:
                    try:
                        element.evaluate("(candidate) => candidate.click()")
                    except Exception:
                        try:
                            element.click(force=True)
                        except TypeError:
                            element.click()
                return self._save_download_event(pending.value, request)
            except Exception as exc:
                # A click can navigate to a sandbox link without emitting a
                # Playwright download event, or open ChatGPT's artifact preview
                # in either the current tab or a newly-created tab. A rate-limit
                # modal also surfaces here; misclassifying it as a download
                # failure burns retries, so check and raise first.
                if self._rate_limit_visible():
                    dismissed = self._dismiss_rate_limit_modal()
                    detail = "acknowledged" if dismissed else "still visible"
                    raise RateLimitError(
                        f"ChatGPT blocked the artifact download with a rate-limit dialog ({detail}).",
                        retry_after=RATE_LIMIT_RECHECK_RETRY_SECONDS,
                    ) from exc
                detail = str(exc).splitlines()[0].strip()
                suffix = f" ({detail})" if detail else ""
                self._download_fallbacks += 1
                self._last_fallback_reason = detail or "download event not emitted"
                _log(
                    "Patchright direct download event was not emitted; "
                    f"checking artifact preview/fallback{suffix}."
                )
            selectors = (
                "button[aria-label*='Download' i]",
                "button[title*='Download' i]",
                "button[data-testid*='download' i]",
                "[role='button'][aria-label*='Download' i]",
                "[role='button'][title*='Download' i]",
                "a[download]",
            )
            preview_deadline = time.monotonic() + min(30, request.timeout)
            while time.monotonic() < preview_deadline:
                current_pages = tuple(getattr(self._context, "pages", (self._page,)))
                # Newly-created preview tabs are searched first, followed by
                # the original page/modal. This mirrors ChatGPT's current UI.
                new_pages = [page for page in current_pages if page not in before_pages]
                preview_pages = list(reversed(new_pages)) + [
                    page for page in reversed(current_pages) if page not in new_pages
                ]
                for preview_page in preview_pages:
                    preview_root = preview_page
                    try:
                        modal = preview_page.locator(
                            "#modal-code-execution, [data-testid='modal-code-execution']"
                        ).last
                        if _locator_visible(modal):
                            preview_root = modal
                    except Exception:
                        pass
                    for selector in selectors:
                        try:
                            preview = preview_root.locator(selector).last
                            if not _locator_visible(preview):
                                continue
                            label = (
                                str(preview.get_attribute("aria-label") or "")
                                or str(preview.get_attribute("title") or "")
                                or str(preview.inner_text() or "")
                            ).strip()
                            if "download" not in label.lower() and selector != "a[download]":
                                continue
                            with preview_page.expect_download(
                                timeout=max(1000, min(30_000, request.timeout * 1000))
                            ) as pending:
                                try:
                                    preview.evaluate("(element) => element.click()")
                                except Exception:
                                    preview.click()
                            return self._save_download_event(pending.value, request)
                        except Exception as exc:
                            _log(f"Patchright preview download miss: {exc}")
                            continue
                time.sleep(0.5)
        return None

    def resolve_download(self, request: DownloadRequest) -> Path | None:
        self._set_state(SessionState.DOWNLOADING)
        try:
            if request.click:
                event_result = self._event_download(request)
                if event_result is not None:
                    self._set_state(SessionState.READY)
                    return event_result
            fallback = salvage_download(
                self._download_dir,
                request.before,
                expected_extensions=request.expected_extensions,
                started_at_ns=request.started_at_ns,
                timeout=request.timeout,
            )
            self._set_state(SessionState.READY)
            return fallback
        except Exception as exc:
            self._set_state(SessionState.FAILED)
            raise self._translate_failure("download", exc) from exc

    def latest_assistant_text(self) -> str:
        try:
            locator = self._page.locator(ASSISTANT_MESSAGE_SELECTOR)
            if int(locator.count()) > 0:
                text = str(locator.last.inner_text() or "").strip()
                if text:
                    return text
            return _body_text(self._page)
        except Exception as exc:
            raise self._translate_failure("diagnostics", exc) from exc

    def save_screenshot(self, path: Path) -> bool:
        try:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._page.screenshot(path=str(path), full_page=True)
            return path.exists()
        except Exception:
            return False

    def get_page_source(self) -> str:
        try:
            return str(self._page.content())
        except Exception as exc:
            raise self._translate_failure("diagnostics", exc) from exc

    def get_cookies(self) -> Sequence[Mapping[str, Any]]:
        try:
            return tuple(self._context.cookies())
        except Exception as exc:
            raise self._translate_failure("cookies", exc) from exc

    def delete_cookie(self, name: str) -> None:
        try:
            cookies = [cookie for cookie in self._context.cookies() if cookie.get("name") != name]
            self._context.clear_cookies()
            if cookies:
                self._context.add_cookies(cookies)
        except Exception as exc:
            raise self._translate_failure("cookies", exc) from exc


class PatchrightProvider:
    name = "patchright"

    @staticmethod
    def _profile_dir(options: BrowserLaunchOptions) -> Path:
        value = options.profile_dir or Path(
            os.environ.get("CHATGPT_PATCHRIGHT_PROFILE_DIR", DEFAULT_PROFILE_DIR)
        )
        return Path(value).expanduser().resolve()

    @staticmethod
    def _download_dir(options: BrowserLaunchOptions) -> Path:
        value = options.download_dir or Path(
            os.environ.get("CHATGPT_DOWNLOAD_DIR", DEFAULT_DOWNLOAD_DIR)
        )
        return Path(value).expanduser().resolve()

    def open_session(self, options: BrowserLaunchOptions | None = None) -> PatchrightBrowserSession:
        options = options or BrowserLaunchOptions()
        normalized_browser = options.browser.strip().lower()
        if normalized_browser not in {"chrome", "chromium", "edge", "msedge"}:
            raise BrowserConfigurationError(
                f"Patchright supports Chromium-based browsers only, not {options.browser!r}."
            )
        profile_dir = self._profile_dir(options)
        download_dir = self._download_dir(options)
        profile_dir.mkdir(parents=True, exist_ok=True)
        download_dir.mkdir(parents=True, exist_ok=True)

        sync_api = _load_patchright()
        playwright = None
        context = None
        try:
            playwright = sync_api.sync_playwright().start()
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(profile_dir),
                "headless": options.headless,
                "accept_downloads": True,
                "downloads_path": str(download_dir),
                "no_viewport": True,
                # The reference-login browser uses the desktop keyring. Keep
                # Chromium on that same cookie-encryption backend; Patchright's
                # defaults otherwise force a mock keychain and make a valid
                # copied ChatGPT session appear signed out.
                "ignore_default_args": [
                    "--password-store=basic",
                    "--use-mock-keychain",
                ],
                "args": [
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-dev-shm-usage",
                    f"--window-size={options.width},{options.height}",
                ],
            }
            executable = _system_chromium_path()
            if executable:
                launch_kwargs["executable_path"] = executable
                _log(f"Patchright using Chromium executable: {executable}")
            elif normalized_browser in {"chrome", "edge", "msedge"}:
                launch_kwargs["channel"] = "msedge" if normalized_browser in {"edge", "msedge"} else "chrome"

            try:
                context = playwright.chromium.launch_persistent_context(**launch_kwargs)
            except Exception as channel_error:
                # Controlled fallback for machines that have Patchright's bundled
                # Chromium installed but no system Chrome/Edge channel.
                if "channel" not in launch_kwargs:
                    raise
                fallback = dict(launch_kwargs)
                fallback.pop("channel", None)
                _log(f"Patchright channel launch failed; trying bundled Chromium: {channel_error}")
                context = playwright.chromium.launch_persistent_context(**fallback)

            context.set_default_timeout(options.action_timeout * 1000)
            context.set_default_navigation_timeout(options.navigation_timeout * 1000)
            if options.use_stealth:
                _apply_stealth(context)
            pages = list(context.pages)
            page = pages[0] if pages else context.new_page()
            session = PatchrightBrowserSession(
                playwright=playwright,
                context=context,
                page=page,
                options=options,
                profile_dir=profile_dir,
                download_dir=download_dir,
            )
            session.set_window_size(options.width, options.height)
            if options.url:
                session.navigate(options.url)
            return session
        except Exception as exc:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass
            try:
                if playwright is not None:
                    playwright.stop()
            except Exception:
                pass
            raise translate_patchright_error("start", exc) from exc

    def wrap_handle(self, handle: object) -> BrowserSession:
        if isinstance(handle, PatchrightBrowserSession):
            return handle
        raise UnsupportedBrowserCapability(
            "A raw Patchright Page cannot be wrapped safely because its persistent "
            "context, profile and download ownership are unknown."
        )
