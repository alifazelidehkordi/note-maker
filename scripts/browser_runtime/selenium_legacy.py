from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pyperclip
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/google-chrome-stable"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path("/snap/bin/chromium"),
]
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path("/usr/bin/microsoft-edge"),
    Path("/usr/bin/microsoft-edge-stable"),
]
CHROME_NAMES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
]
EDGE_NAMES = ["microsoft-edge", "microsoft-edge-stable"]
CHROME_PROFILE_DIR = ROOT / "chrome_profile"
EDGE_PROFILE_DIR = ROOT / "edge_profile"
DOWNLOAD_DIR = ROOT / "downloads"
TEXT_OUTPUT = ROOT / "last_response.txt"
SCREENSHOT = ROOT / "last_state.png"
LOG_FILE = ROOT / "run.log"
CHATGPT_URL = "https://chatgpt.com/?temporary-chat=true"
SEND_SELECTORS = [
    "button[data-testid='send-button']",
    "button[data-testid='composer-send-button']",
    "button[aria-label='Send prompt']",
    "button[aria-label='Send message']",
    "button[aria-label*='Send']",
    "button[aria-label*='send']",
]


def log(message: str) -> None:
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def find_browser_binary(candidates: list[Path], names: list[str]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def pyautogui_module():
    import pyautogui

    return pyautogui


def paste_hotkey() -> None:
    modifier = "command" if sys.platform == "darwin" else "ctrl"
    pyautogui_module().hotkey(modifier, "v")


def _build_driver_with_paths(
    *,
    headless: bool = False,
    browser: str = "chrome",
    profile_dir: Path | None = None,
    download_dir: Path | None = None,
):
    effective_download_dir = Path(download_dir or os.environ.get("CHATGPT_DOWNLOAD_DIR", DOWNLOAD_DIR)).expanduser().resolve()
    effective_download_dir.mkdir(parents=True, exist_ok=True)

    if browser == "edge":
        profile_dir = Path(profile_dir or os.environ.get("CHATGPT_EDGE_PROFILE_DIR", EDGE_PROFILE_DIR))
        options = EdgeOptions()
        binary = find_browser_binary(EDGE_CANDIDATES, EDGE_NAMES)
        if binary is None:
            raise RuntimeError(
                "Microsoft Edge was not found. Install Edge or run with --browser chrome."
            )
        options.binary_location = str(binary)
        service = EdgeService()
        driver_factory = webdriver.Edge
    else:
        profile_dir = Path(profile_dir or os.environ.get("CHATGPT_CHROME_PROFILE_DIR", CHROME_PROFILE_DIR))
        options = ChromeOptions()
        binary = find_browser_binary(CHROME_CANDIDATES, CHROME_NAMES)
        if binary is None:
            raise RuntimeError(
                "Chrome/Chromium was not found. Install one of: google-chrome, chromium-browser"
            )
        options.binary_location = str(binary)
        service = ChromeService()
        driver_factory = webdriver.Chrome

    profile_dir.mkdir(parents=True, exist_ok=True)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(effective_download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    if headless:
        options.add_argument("--headless=new")

    log(f"Launching browser: {browser}, profile: {profile_dir}")
    return driver_factory(service=service, options=options)


def build_driver(headless: bool = False, browser: str = "chrome"):
    """Compatibility entry point preserving the Level 1 public signature."""
    return _build_driver_with_paths(headless=headless, browser=browser)


def wait_for_editor(driver: webdriver.Edge, timeout: int = 120):
    selectors = [
        (By.CSS_SELECTOR, "#prompt-textarea"),
        (By.CSS_SELECTOR, "div[contenteditable='true'][data-placeholder]"),
        (By.CSS_SELECTOR, "div[contenteditable='true']"),
        (By.CSS_SELECTOR, "textarea"),
    ]
    end = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < end:
        for by, selector in selectors:
            try:
                element = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((by, selector))
                )
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception as exc:
                last_error = exc
        time.sleep(1)
    raise TimeoutException(f"Could not find ChatGPT prompt editor: {last_error}")


def dismiss_cookie_banner(driver: webdriver.Edge) -> None:
    labels = ["Accept all", "Reject non-essential"]
    for label in labels:
        buttons = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{label}')]")
        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled():
                    log(
                        "Clicking attach button: "
                        f"aria-label={button.get_attribute('aria-label')!r}, "
                        f"data-testid={button.get_attribute('data-testid')!r}"
                    )
                    button.click()
                    time.sleep(1)
                    return
            except Exception:
                continue


def login_buttons_visible(driver: webdriver.Edge) -> bool:
    buttons = driver.find_elements(
        By.XPATH,
        "//button[contains(normalize-space(.), 'Log in') or contains(normalize-space(.), 'Sign up')]"
        " | //a[contains(normalize-space(.), 'Log in') or contains(normalize-space(.), 'Sign up')]",
    )
    return any(button.is_displayed() for button in buttons)


PAGE_LOAD_ERROR_MARKERS = (
    "HTTP ERROR 431",
    "This page isn",
    "This page isn't working",
)


def visible_body_text(driver: webdriver.Edge) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return ""


def page_has_load_error(driver: webdriver.Edge) -> bool:
    body_text = visible_body_text(driver)
    return any(marker in body_text for marker in PAGE_LOAD_ERROR_MARKERS)


def reload_and_wait_for_editor(driver: webdriver.Edge, timeout: int = 45) -> bool:
    driver.refresh()
    try:
        wait_for_editor(driver, timeout=timeout)
        return True
    except TimeoutException:
        return False


def wait_until_logged_in(driver: webdriver.Edge, timeout: int = 600) -> None:
    deadline = time.time() + timeout
    warned = False
    while time.time() < deadline:
        dismiss_cookie_banner(driver)
        if not login_buttons_visible(driver):
            try:
                wait_for_editor(driver, timeout=30)
                return
            except TimeoutException:
                if page_has_load_error(driver):
                    log("ChatGPT page did not load cleanly during login check; reloading.")
                else:
                    log("ChatGPT editor not visible yet; reloading and retrying login check.")
                if reload_and_wait_for_editor(driver, timeout=45):
                    return
                time.sleep(2)
                continue
        if not warned:
            log("Login is required. Please log in in the opened browser window.")
            warned = True
        time.sleep(3)
    raise TimeoutException("Timed out waiting for ChatGPT login.")


def start_new_chat(driver: webdriver.Edge) -> None:
    log("Starting a new temporary chat.")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        driver.get(CHATGPT_URL)
        try:
            wait_for_editor(driver, timeout=60)
            return
        except TimeoutException as exc:
            last_error = exc
            reason = "load error" if page_has_load_error(driver) else "missing editor"
            log(f"Temporary chat did not load ({reason}); reloading page ({attempt}/3).")
            if reload_and_wait_for_editor(driver, timeout=45):
                return
            time.sleep(2)
    raise TimeoutException(f"Could not load temporary chat after retries: {last_error}")


def select_model(driver: webdriver.Edge, model_label: str | None = None) -> None:
    if not model_label:
        return

    try:
        log(f"Selecting model: {model_label}")
        lower_label = model_label.lower()
        avoid_mini = "mini" not in lower_label

        opener_xpaths = [
            "//button[contains(@data-testid, 'model')]",
            "//button[contains(@aria-label, 'model') or contains(@aria-label, 'Model')]",
            "//button[contains(normalize-space(.), 'GPT')]",
            "//button[contains(normalize-space(.), '5.3')]",
            "//button[contains(normalize-space(.), 'mini')]",
            "//button[contains(normalize-space(.), 'Auto')]",
            "//button[contains(normalize-space(.), 'Medium')]",
            "//button[contains(normalize-space(.), 'Fast')]",
            "//button[contains(normalize-space(.), 'Thinking')]",
        ]

        opened = False
        for xpath in opener_xpaths:
            for button in driver.find_elements(By.XPATH, xpath):
                try:
                    if button.is_displayed() and button.is_enabled():
                        log(
                            "Opening model selector: "
                            f"text={button.text!r}, aria-label={button.get_attribute('aria-label')!r}, "
                            f"data-testid={button.get_attribute('data-testid')!r}"
                        )
                        driver.execute_script("arguments[0].click();", button)
                        time.sleep(1)
                        opened = True
                        break
                except Exception:
                    continue
            if opened:
                break

        if not opened:
            log("Could not find a model selector button. Proceeding with current/default model.")
            return

        option_xpaths = [
            "//*[@role='menuitem' or @role='option' or self::button or self::div]",
        ]
        candidates = []
        for xpath in option_xpaths:
            for element in driver.find_elements(By.XPATH, xpath):
                try:
                    text = (element.text or "").strip()
                    text_lower = text.lower()
                    if not text or lower_label not in text_lower:
                        continue
                    if avoid_mini and "mini" in text_lower:
                        continue
                    if element.is_displayed():
                        candidates.append((len(text), text, element))
                except Exception:
                    continue

        if not candidates:
            log(f"Could not find requested model option '{model_label}'. Proceeding with current model.")
            return

        _, text, element = sorted(candidates, key=lambda item: item[0])[0]
        log(f"Clicking model option: {text!r}")
        driver.execute_script("arguments[0].click();", element)
        time.sleep(2)
    except Exception as e:
        log(f"Model selection failed or not needed ({e}). Proceeding with whatever model is active.")


def set_editor_text(driver: webdriver.Edge, text: str) -> None:
    editor = wait_for_editor(driver)
    driver.execute_script(
        """
        const el = arguments[0];
        el.focus();
        // Clear existing text first
        if (el.tagName === 'TEXTAREA') {
            el.value = '';
        } else {
            el.innerText = '';
        }
        // Insert text using insertText command to trigger React input handlers
        document.execCommand('insertText', false, arguments[1]);
        """,
        editor,
        text,
    )


def editor_text(driver: webdriver.Edge) -> str:
    editor = wait_for_editor(driver)
    return driver.execute_script(
        """
        const el = arguments[0];
        return el.tagName === 'TEXTAREA' ? el.value : el.innerText;
        """,
        editor,
    ) or ""


def find_enabled_send_button(driver: webdriver.Edge):
    for selector in SEND_SELECTORS:
        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
        for button in buttons:
            disabled = button.get_attribute("disabled")
            aria_disabled = button.get_attribute("aria-disabled")
            if (
                button.is_displayed()
                and button.is_enabled()
                and disabled is None
                and aria_disabled != "true"
            ):
                return button
    return None


def wait_for_send_enabled(driver: webdriver.Edge, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if find_enabled_send_button(driver) is not None:
            return
        time.sleep(1)
    raise TimeoutException("Timed out waiting for the send button to become enabled.")


def click_send(driver: webdriver.Edge) -> None:
    wait_for_send_enabled(driver)
    button = find_enabled_send_button(driver)
    if button is not None:
        log(
            "Clicking send button: "
            f"aria-label={button.get_attribute('aria-label')!r}, "
            f"data-testid={button.get_attribute('data-testid')!r}"
        )
        driver.execute_script("arguments[0].click();", button)
        return
    raise RuntimeError("No enabled ChatGPT send button found.")


def send_message(driver: webdriver.Edge, text: str) -> None:
    set_editor_text(driver, text)
    time.sleep(0.5)
    for attempt in range(3):
        click_send(driver)
        deadline = time.time() + 20
        while time.time() < deadline:
            current = editor_text(driver).strip()
            if not current:
                log("Message was submitted; composer is empty.")
                return
            time.sleep(1)
        log(f"Send click did not clear composer; retrying ({attempt + 1}/3).")
    raise TimeoutException("Message did not submit; composer still contains text.")


def assistant_message_count(driver: webdriver.Edge) -> int:
    return len(
        [
            el
            for el in driver.find_elements(By.CSS_SELECTOR, "[data-message-author-role='assistant']")
            if el.is_displayed()
        ]
    )


def wait_until_idle(driver: webdriver.Edge, timeout: int = 600, min_assistant_count: int | None = None) -> None:
    log("Waiting for ChatGPT response to finish...")
    deadline = time.time() + timeout
    stable_since: float | None = None
    last_text = ""
    saw_required_response = min_assistant_count is None

    while time.time() < deadline:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if min_assistant_count is not None and assistant_message_count(driver) >= min_assistant_count:
            saw_required_response = True

        generating_controls = driver.find_elements(
            By.CSS_SELECTOR,
            "button[data-testid='stop-button'], button[aria-label*='Stop'], button[aria-label*='stop']",
        )
        is_generating = any(button.is_displayed() for button in generating_controls)

        if saw_required_response and body_text == last_text and not is_generating:
            stable_since = stable_since or time.time()
            if time.time() - stable_since >= 8:
                return
        else:
            stable_since = None
            last_text = body_text

        time.sleep(2)

    raise TimeoutException("Timed out while waiting for ChatGPT to finish.")


def wait_until_editor_ready(driver: webdriver.Edge, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            editor = wait_for_editor(driver, timeout=5)
            stop_buttons = driver.find_elements(
                By.CSS_SELECTOR,
                "button[data-testid='stop-button'], button[aria-label*='Stop'], button[aria-label*='stop']",
            )
            has_visible_stop = any(button.is_displayed() for button in stop_buttons)
            if editor.is_displayed() and editor.is_enabled() and not has_visible_stop:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutException("Timed out waiting for the chat box to become ready.")


def click_attach_menu(driver: webdriver.Edge) -> None:
    selectors = [
        "button[data-testid='composer-plus-btn']",
        "button[aria-label*='Attach']",
        "button[aria-label*='attach']",
        "button[aria-label*='Upload']",
        "button[aria-label*='upload']",
        "button[aria-label*='Add photos']",
        "button[aria-label*='Add files']",
    ]
    for selector in selectors:
        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
        for button in buttons:
            try:
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    time.sleep(1)
                    return
            except Exception:
                continue

    # Last-resort coordinate fallback for the plus button in the composer.
    log("Attach button selector not found; using coordinate fallback.")
    rect = driver.get_window_rect()
    pyautogui_module().click(rect["x"] + 450, rect["y"] + 910)
    time.sleep(1)


def native_attach_file(driver: webdriver.Edge, file_path: Path) -> None:
    file_path = Path(file_path).resolve()
    log(f"Uploading via native file picker: {file_path.name}")
    driver.execute_script("window.focus();")
    click_attach_menu(driver)

    menu_xpaths = [
        "//button[contains(normalize-space(.), 'Upload from computer')]",
        "//*[@role='menuitem'][contains(normalize-space(.), 'Upload from computer')]",
        "//button[contains(normalize-space(.), 'Upload file')]",
        "//*[@role='menuitem'][contains(normalize-space(.), 'Upload file')]",
        "//button[contains(normalize-space(.), 'Add photos & files')]",
        "//*[@role='menuitem'][contains(normalize-space(.), 'Add photos & files')]",
        "//button[contains(normalize-space(.), 'Add photos and files')]",
        "//*[@role='menuitem'][contains(normalize-space(.), 'Add photos and files')]",
        "//button[contains(normalize-space(.), 'Add files')]",
        "//*[@role='menuitem'][contains(normalize-space(.), 'Add files')]",
    ]
    clicked = False
    for xpath in menu_xpaths:
        for item in driver.find_elements(By.XPATH, xpath):
            try:
                if item.is_displayed():
                    log(f"Clicking upload menu item: {item.text!r}")
                    item.click()
                    clicked = True
                    break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        visible_text = driver.find_element(By.TAG_NAME, "body").text
        log("Upload menu item was not found. Visible page text tail:")
        log(visible_text[-1000:])
        raise RuntimeError("Could not find an upload menu item after opening the attach menu.")

    time.sleep(1.5)
    pyperclip.copy(str(file_path))
    paste_hotkey()
    pyautogui_module().press("enter")
    log("Waiting for upload to finish...")
    time.sleep(5)


def dom_attach_file(driver: webdriver.Edge, file_path: Path) -> None:
    file_path = Path(file_path).resolve()
    log(f"Uploading: {file_path.name}")
    inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not inputs:
        # Opening the attach menu often inserts the hidden file input into the DOM.
        attach_selectors = [
            "button[aria-label*='Attach']",
            "button[aria-label*='Upload']",
            "button[data-testid*='attach']",
            "button[data-testid*='upload']",
        ]
        for selector in attach_selectors:
            buttons = driver.find_elements(By.CSS_SELECTOR, selector)
            for button in buttons:
                if button.is_displayed() and button.is_enabled():
                    button.click()
                    time.sleep(1)
                    break
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if inputs:
                break

    if not inputs:
        raise RuntimeError("Could not find a file upload input on the ChatGPT page.")

    def collect_usable_file_inputs(current_inputs):
        usable = []
        for index, input_el in enumerate(current_inputs):
            accept = input_el.get_attribute("accept") or ""
            multiple = input_el.get_attribute("multiple")
            aria_label = input_el.get_attribute("aria-label")
            accept_lower = accept.lower()
            log(
                f"File input {index}: accept={accept!r}, multiple={multiple!r}, "
                f"aria-label={aria_label!r}"
            )
            if (
                accept.strip() in {"", "*/*"}
                or ".md" in accept_lower
                or ".txt" in accept_lower
                or ".pdf" in accept_lower
                or "text/" in accept_lower
                or "application" in accept_lower
            ):
                usable.append(input_el)
        return usable

    usable_inputs = collect_usable_file_inputs(inputs)
    if not usable_inputs:
        log("No general file input found; opening attach menu and retrying file input discovery.")
        click_attach_menu(driver)
        time.sleep(1)
        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        usable_inputs = collect_usable_file_inputs(inputs)

    if not usable_inputs:
        raise RuntimeError("Could not find a non-image file upload input for this document.")

    target = usable_inputs[-1]
    target.send_keys(str(file_path))
    log("Waiting for upload to finish...")
    time.sleep(3)


def attach_file(driver: webdriver.Edge, file_path: Path, native_upload: bool = False) -> None:
    if native_upload:
        native_attach_file(driver, file_path)
    else:
        dom_attach_file(driver, file_path)


def upload_pending_visible(driver: webdriver.Edge) -> bool:
    body_text = driver.find_element(By.TAG_NAME, "body").text.lower()
    pending_markers = [
        "file upload pending",
        "upload pending",
        "uploading",
        "processing file",
    ]
    return any(marker in body_text for marker in pending_markers)


def wait_for_file_upload_complete(driver: webdriver.Edge, file_path: Path, timeout: int = 600) -> None:
    expected_bits = [file_path.name[:24], file_path.stem[:24]]
    deadline = time.time() + timeout
    saw_file = False
    last_log = 0.0

    while time.time() < deadline:
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if any(bit and bit in body_text for bit in expected_bits):
            saw_file = True

        pending = upload_pending_visible(driver)
        if time.time() - last_log >= 20:
            if saw_file and pending:
                log("File is visible; still waiting for upload to finish...")
            elif saw_file:
                log("File is visible; checking upload state...")
            else:
                log("Waiting for file attachment to appear...")
            last_log = time.time()

        if saw_file and not pending:
            time.sleep(3)
            if not upload_pending_visible(driver):
                log("File upload appears complete.")
                return

        time.sleep(1)

    raise TimeoutException("Timed out waiting for the PDF upload to complete.")


PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")
NON_FILE_DOWNLOAD_PHRASES = (
    "download apps",
    "get chatgpt mobile",
    "chatgpt mobile",
    "app store",
    "google play",
)

# Supported downloadable artifacts from ChatGPT. Markdown has two equivalent
# filename extensions, while OPML is intentionally kept as a separate type.
ARTIFACT_EXTENSIONS = frozenset({".opml", ".md", ".markdown"})
MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
DOWNLOAD_TIME_TOLERANCE_NS = 2_000_000_000
DownloadSnapshot = dict[Path, tuple[int, int] | None]


def normalize_expected_extensions(
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str] | None,
) -> frozenset[str]:
    """Normalize and validate the artifact extensions accepted by a job."""
    if expected_extensions is None:
        return ARTIFACT_EXTENSIONS

    normalized = set()
    for extension in expected_extensions:
        value = str(extension).strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = "." + value
        if value not in ARTIFACT_EXTENSIONS:
            raise ValueError(f"Unsupported artifact extension: {extension}")
        normalized.add(value)

    if not normalized:
        raise ValueError("At least one expected artifact extension is required.")
    return frozenset(normalized)


def accepted_artifact_suffixes(
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str] | None,
) -> frozenset[str]:
    """Return filename suffixes equivalent to the requested artifact types."""
    expected = normalize_expected_extensions(expected_extensions)
    accepted = set(expected)
    if expected & MARKDOWN_EXTENSIONS:
        accepted.update(MARKDOWN_EXTENSIONS)
    return frozenset(accepted)


def is_partial_download(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def _file_state(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def snapshot_downloads(directory: Path | None = None) -> DownloadSnapshot:
    """Capture paths plus mtime/size so overwritten downloads are detectable."""
    directory = directory or DOWNLOAD_DIR
    snapshot: DownloadSnapshot = {}
    for path in directory.glob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        state = _file_state(resolved)
        if state is not None:
            snapshot[resolved] = state
    return snapshot


def _normalize_download_snapshot(before: DownloadSnapshot | set[Path]) -> DownloadSnapshot:
    if isinstance(before, dict):
        return {Path(path).resolve(): state for path, state in before.items()}
    # Compatibility with older callers: a set can identify new names but cannot
    # prove that an existing filename was overwritten.
    return {Path(path).resolve(): None for path in before}


def _is_fresh_download(
    path: Path,
    before: DownloadSnapshot | set[Path],
    *,
    started_at_ns: int,
) -> bool:
    resolved = path.resolve()
    state = _file_state(resolved)
    if state is None:
        return False

    snapshot = _normalize_download_snapshot(before)
    previous = snapshot.get(resolved, "missing")
    if previous == state:
        return False
    if previous is None and resolved in snapshot:
        return False

    mtime_ns, _ = state
    if started_at_ns and mtime_ns + DOWNLOAD_TIME_TOLERANCE_NS < started_at_ns:
        return False
    return True


def _content_matches_expected(path: Path, expected_extensions: frozenset[str]) -> bool:
    try:
        if path.stat().st_size > 5_000_000:
            return False
        sample = path.read_text(encoding="utf-8", errors="ignore")[:8192]
    except OSError:
        return False

    lower = sample.lower()
    if ".opml" in expected_extensions and "<opml" in lower:
        return True
    if expected_extensions & MARKDOWN_EXTENSIONS:
        stripped = sample.lstrip()
        if stripped.startswith("#") or "\n## " in sample or "\n### " in sample:
            return True
    return False


def is_artifact_download_file(
    path: Path,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str] | None = None,
) -> bool:
    """Return True only when a file matches the artifact type requested by the job."""
    if not path.is_file() or is_partial_download(path):
        return False

    expected = normalize_expected_extensions(expected_extensions)
    accepted_suffixes = accepted_artifact_suffixes(expected)
    suffix = path.suffix.lower()
    if suffix in accepted_suffixes:
        return True
    if suffix in ARTIFACT_EXTENSIONS:
        return False
    return _content_matches_expected(path, expected)


def is_opml_download_file(path: Path) -> bool:
    """Backward-compatible OPML-specific helper."""
    return is_artifact_download_file(path, {".opml"})


def _has_expected_reference(haystack: str, expected: frozenset[str]) -> bool:
    accepted = accepted_artifact_suffixes(expected)
    if any(extension in haystack for extension in accepted):
        return True
    if ".opml" in expected and re.search(r"\bopml\b", haystack):
        return True
    if expected & MARKDOWN_EXTENSIONS and re.search(r"\bmarkdown\b", haystack):
        return True
    return False


def is_artifact_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str] | None = None,
) -> bool:
    """Detect a download control only when it names the expected artifact type."""
    expected = normalize_expected_extensions(expected_extensions)
    direct = " ".join(field for field in (text, href, title, aria) if field)
    direct_haystack = direct.lower()
    context_haystack = context.lower()
    full_haystack = f"{direct_haystack} {context_haystack}".strip()
    if any(phrase in full_haystack for phrase in NON_FILE_DOWNLOAD_PHRASES):
        return False

    if _has_expected_reference(direct_haystack, expected):
        return True

    # A plain Download button is valid only when the surrounding artifact card
    # names the expected format. Unrelated controls such as "Coding Citation"
    # must not inherit format words from the whole assistant message.
    explicit_download = "download" in direct_haystack or "دانلود" in direct
    return (
        explicit_download and _has_expected_reference(context_haystack, expected)
    ) or direct_haystack.strip() in {"download", "دانلود"}


def is_opml_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
) -> bool:
    """Backward-compatible OPML-specific trigger helper."""
    return is_artifact_download_trigger(
        text=text,
        href=href,
        title=title,
        aria=aria,
        context=context,
        expected_extensions={".opml"},
    )


def _fresh_download_files(
    before: DownloadSnapshot | set[Path],
    *,
    started_at_ns: int,
    include_partial: bool,
) -> list[Path]:
    files: list[Path] = []
    for path in DOWNLOAD_DIR.glob("*"):
        if not path.is_file():
            continue
        if is_partial_download(path) != include_partial:
            continue
        if _is_fresh_download(path, before, started_at_ns=started_at_ns):
            files.append(path.resolve())
    return files


def newest_download(
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
) -> Path | None:
    candidates = [
        path
        for path in _fresh_download_files(
            before,
            started_at_ns=started_at_ns,
            include_partial=False,
        )
        if is_artifact_download_file(path, expected_extensions)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def pending_downloads(
    before: DownloadSnapshot | set[Path],
    *,
    started_at_ns: int,
) -> list[Path]:
    return sorted(
        _fresh_download_files(
            before,
            started_at_ns=started_at_ns,
            include_partial=True,
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )


def wait_for_download_settled(
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
    timeout: int = 90,
) -> Path | None:
    """Wait for a fresh, settled download matching the requested artifact type."""
    deadline = time.time() + timeout
    last_size: dict[str, int] = {}
    last_logged = 0.0

    while time.time() < deadline:
        partial = pending_downloads(before, started_at_ns=started_at_ns)
        if partial:
            for path in partial:
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                key = str(path)
                if last_size.get(key) == size and not key.endswith(".crdownload"):
                    continue
                last_size[key] = size
            if time.time() - last_logged > 10:
                log(f"Download in progress: {[p.name for p in partial]}")
                last_logged = time.time()
            time.sleep(1.0)
            continue

        downloaded = newest_download(
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
        )
        if downloaded:
            return downloaded

        candidates = find_artifact_candidates_in_downloads(
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
        )
        if candidates:
            return candidates[0]
        time.sleep(1.0)

    return newest_download(
        before,
        expected_extensions=expected_extensions,
        started_at_ns=started_at_ns,
    ) or (
        find_artifact_candidates_in_downloads(
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
        )
        or [None]
    )[0]


def find_artifact_candidates_in_downloads(
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
) -> list[Path]:
    """Return fresh files whose suffix or content matches the expected type."""
    candidates = [
        path
        for path in _fresh_download_files(
            before,
            started_at_ns=started_at_ns,
            include_partial=False,
        )
        if is_artifact_download_file(path, expected_extensions)
    ]
    return sorted(candidates, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def find_opml_candidates_in_downloads(
    before: DownloadSnapshot | set[Path],
    *,
    started_at_ns: int,
) -> list[Path]:
    """Backward-compatible OPML-specific candidate search."""
    return find_artifact_candidates_in_downloads(
        before,
        expected_extensions={".opml"},
        started_at_ns=started_at_ns,
    )


def element_download_fields(element) -> tuple[str, str, str, str, str]:
    text = element.text or ""
    href = element.get_attribute("href") or ""
    title = element.get_attribute("title") or ""
    aria = element.get_attribute("aria-label") or ""
    context = ""
    try:
        context = element.find_element(By.XPATH, "./ancestor::*[self::div or self::article][1]").text or ""
    except Exception:
        pass
    return text, href, title, aria, context


def click_candidate_and_wait(
    driver: webdriver.Edge,
    element,
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
) -> Path | None:
    text, href, title, aria, context = element_download_fields(element)
    if not is_artifact_download_trigger(
        text=text,
        href=href,
        title=title,
        aria=aria,
        context=context,
        expected_extensions=expected_extensions,
    ):
        return None

    txt = (text or aria or title or href or "")[:120]
    log(f"Clicking artifact download candidate: {txt!r}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.4)
    driver.execute_script("arguments[0].click();", element)
    deadline = time.time() + 45
    while time.time() < deadline:
        downloaded = wait_for_download_settled(
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
            timeout=3,
        )
        if downloaded:
            log(f"Download detected after click: {downloaded.name}")
            return downloaded
        time.sleep(0.8)
    return None


def _page_wide_download_xpaths(expected_extensions: frozenset[str]) -> list[str]:
    accepted = accepted_artifact_suffixes(expected_extensions)
    xpaths = [f"//a[contains(translate(@href, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{ext}')]" for ext in sorted(accepted)]
    if ".opml" in expected_extensions:
        keyword = "opml"
        xpaths.extend(
            [
                f"//*[@role='link'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]",
                f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]",
            ]
        )
    if expected_extensions & MARKDOWN_EXTENSIONS:
        keyword = "markdown"
        xpaths.extend(
            [
                f"//*[@role='link'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]",
                f"//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{keyword}')]",
            ]
        )
    return xpaths


def click_new_download_link(
    driver: webdriver.Edge,
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
) -> Path | None:
    """Click a download control that matches the job's expected artifact type."""
    expected = normalize_expected_extensions(expected_extensions)

    # Attachment cards and buttons in the latest assistant response have highest
    # priority. Older responses are deliberately ignored to avoid stale artifacts.
    try:
        assistants = driver.find_elements(By.CSS_SELECTOR, "[data-message-author-role='assistant']")
        if assistants:
            latest = assistants[-1]
            elements = latest.find_elements(
                By.CSS_SELECTOR,
                "a[href], button, [role='link'], [role='button']",
            )
            for element in reversed(elements):
                try:
                    if not element.is_displayed():
                        continue
                    downloaded = click_candidate_and_wait(
                        driver,
                        element,
                        before,
                        expected_extensions=expected,
                        started_at_ns=started_at_ns,
                    )
                    if downloaded:
                        return downloaded
                except Exception:
                    continue
    except Exception:
        pass

    # Page-wide fallback is restricted to exact expected extensions or explicit
    # format names. Generic "download file" and "notes" links are not scanned.
    for xpath in _page_wide_download_xpaths(expected):
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for element in reversed(elements):
            try:
                if not element.is_displayed():
                    continue
                downloaded = click_candidate_and_wait(
                    driver,
                    element,
                    before,
                    expected_extensions=expected,
                    started_at_ns=started_at_ns,
                )
                if downloaded:
                    return downloaded
            except Exception:
                continue
    return None


def wait_and_salvage_download(
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
    timeout: int = 90,
) -> Path | None:
    """Wait for an auto-download and salvage only the expected artifact type."""
    deadline = time.time() + timeout
    last_logged = 0.0
    while time.time() < deadline:
        downloaded = wait_for_download_settled(
            before,
            expected_extensions=expected_extensions,
            started_at_ns=started_at_ns,
            timeout=3,
        )
        if downloaded:
            return downloaded
        if time.time() - last_logged > 12:
            partial = pending_downloads(before, started_at_ns=started_at_ns)
            if partial:
                log(f"Still waiting for download to finish: {[p.name for p in partial]}")
            else:
                log("Still waiting for a matching new artifact in downloads/ ...")
            last_logged = time.time()
        time.sleep(1.2)

    candidates = find_artifact_candidates_in_downloads(
        before,
        expected_extensions=expected_extensions,
        started_at_ns=started_at_ns,
    )
    return candidates[0] if candidates else None


def resolve_download(
    driver: webdriver.Edge | None,
    before: DownloadSnapshot | set[Path],
    *,
    expected_extensions: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    started_at_ns: int,
    timeout: int = 90,
    click: bool = True,
) -> Path | None:
    """Resolve a fresh download matching the exact artifact type requested."""
    expected = normalize_expected_extensions(expected_extensions)
    downloaded = None
    if click and driver is not None:
        downloaded = click_new_download_link(
            driver,
            before,
            expected_extensions=expected,
            started_at_ns=started_at_ns,
        )
        if downloaded is None:
            log("First download click pass missed; retrying expected-artifact scan...")
            time.sleep(2)
            downloaded = click_new_download_link(
                driver,
                before,
                expected_extensions=expected,
                started_at_ns=started_at_ns,
            )
    if downloaded is None:
        downloaded = wait_and_salvage_download(
            before,
            expected_extensions=expected,
            started_at_ns=started_at_ns,
            timeout=timeout,
        )
    if downloaded is None:
        candidates = find_artifact_candidates_in_downloads(
            before,
            expected_extensions=expected,
            started_at_ns=started_at_ns,
        )
        if candidates:
            downloaded = candidates[0]
            log(f"Salvaged matching artifact from downloads/: {downloaded.name}")
    return downloaded

def latest_assistant_text(driver: webdriver.Edge) -> str:
    selectors = [
        "[data-message-author-role='assistant']",
        "article",
        "main .markdown",
    ]
    for selector in selectors:
        elements = [
            el
            for el in driver.find_elements(By.CSS_SELECTOR, selector)
            if el.is_displayed() and el.text.strip()
        ]
        if elements:
            return elements[-1].text.strip()
    return driver.find_element(By.TAG_NAME, "body").text.strip()


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def run(
    prompt_path: Path,
    file_path: Path,
    headless: bool = False,
    native_upload: bool = False,
    browser: str = "chrome",
    model: str | None = None,
) -> int:
    LOG_FILE.write_text("", encoding="utf-8")
    if not prompt_path.exists():
        raise FileNotFoundError(prompt_path)
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Prompt file is empty.")

    driver = build_driver(headless=headless, browser=browser)
    try:
        driver.set_window_size(1400, 950)
        driver.get(CHATGPT_URL)
        log("ChatGPT opened.")
        log("Checking login state...")
        wait_until_logged_in(driver)
        log("Logged-in chat box is visible.")
        start_new_chat(driver)
        select_model(driver, model)

        before_downloads = snapshot_downloads()
        attach_file(driver, file_path, native_upload=native_upload)
        wait_for_file_upload_complete(driver, file_path)
        log("Sending the exact prompt text with the uploaded file...")
        expected_assistant_count = assistant_message_count(driver) + 1
        download_started_at_ns = time.time_ns()
        send_message(driver, prompt)
        wait_until_idle(driver, min_assistant_count=expected_assistant_count)

        downloaded = resolve_download(
            driver,
            before_downloads,
            expected_extensions={".opml"},
            started_at_ns=download_started_at_ns,
            timeout=50,
        )

        response_text = latest_assistant_text(driver)

        TEXT_OUTPUT.write_text(response_text, encoding="utf-8")
        driver.save_screenshot(str(SCREENSHOT))

        log(f"Saved response text: {TEXT_OUTPUT}")
        log(f"Saved screenshot: {SCREENSHOT}")
        if downloaded:
            final_name = ROOT / f"{safe_filename(file_path.stem)}.opml"
            if final_name.exists():
                final_name.unlink()
            downloaded.replace(final_name)
            log(f"Downloaded file saved as: {final_name}")
        else:
            log(f"No downloadable file was detected. Check downloads folder: {DOWNLOAD_DIR}")
            log("   (In the open browser window: click any Download / OPML / file link that appeared in the chat. It will usually land in downloads/ )")

        return 0
    finally:
        log("Leaving the browser open for inspection for 20 seconds...")
        time.sleep(20)
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--file", type=Path, required=True, help="PDF or DOCX file to convert")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--native-upload", action="store_true")
    parser.add_argument("--browser", choices=["chrome", "edge"], default="chrome")
    parser.add_argument("--model", default=None, help="Optional model label. Leave empty to use whatever is selected in the browser (or use --manual-start in batch).")
    args = parser.parse_args()

    try:
        return run(
            args.prompt,
            args.file,
            args.headless,
            native_upload=args.native_upload,
            browser=args.browser,
            model=args.model,
        )
    except Exception as exc:
        log(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
