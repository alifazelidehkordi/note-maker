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


ROOT = Path(__file__).resolve().parent.parent
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


def build_driver(headless: bool = False, browser: str = "chrome"):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if browser == "edge":
        profile_dir = Path(os.environ.get("CHATGPT_EDGE_PROFILE_DIR", EDGE_PROFILE_DIR))
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
        profile_dir = Path(os.environ.get("CHATGPT_CHROME_PROFILE_DIR", CHROME_PROFILE_DIR))
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
            "download.default_directory": str(DOWNLOAD_DIR),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    if headless:
        options.add_argument("--headless=new")

    log(f"Launching browser: {browser}, profile: {profile_dir}")
    return driver_factory(service=service, options=options)


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

# Supported downloadable artifacts from ChatGPT (mind maps use .opml, note rewriting uses .md)
ARTIFACT_EXTENSIONS = (".opml", ".md", ".markdown")


def is_partial_download(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def is_artifact_download_file(path: Path) -> bool:
    """Return True if the file looks like a ChatGPT-generated artifact (.opml or .md etc)."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if any(ext in name or suffix == ext for ext in ARTIFACT_EXTENSIONS):
        return True
    try:
        if path.stat().st_size > 5_000_000:
            return False
        sample = path.read_text(encoding="utf-8", errors="ignore")[:4096].lower()
    except OSError:
        return False

    # Legacy OPML detection
    if "<opml" in sample:
        return True

    # Heuristic for Markdown rewrite output
    stripped = sample.strip()
    if stripped.startswith("#") or "\n## " in sample or "\n### " in sample:
        return True
    return False


# Back-compat alias (existing code may call the old name)
is_opml_download_file = is_artifact_download_file


def is_artifact_download_trigger(
    *,
    text: str = "",
    href: str = "",
    title: str = "",
    aria: str = "",
    context: str = "",
) -> bool:
    """Detect likely download links for ChatGPT generated artifacts (works for both OPML and Markdown)."""
    fields = [text, href, title, aria, context]
    haystack = " ".join(field.lower() for field in fields if field)
    if any(phrase in haystack for phrase in NON_FILE_DOWNLOAD_PHRASES):
        return False

    href_lower = href.lower()
    # Direct mentions
    if any(ext in haystack for ext in (".opml", ".md", "markdown", "notes", "file")):
        return True
    if "opml" in haystack:
        return True
    # Sandbox and generic attachment downloads are the most reliable signals
    if href_lower.startswith("sandbox:") or "sandbox:" in href_lower:
        return True
    if "attachment" in href_lower and "download" in haystack:
        return True
    if "/download" in href_lower and any(token in haystack for token in ("file", "attachment", "download", "notes")):
        return True
    return False


# Back-compat alias
is_opml_download_trigger = is_artifact_download_trigger


def newest_download(before: set[Path]) -> Path | None:
    current = set(DOWNLOAD_DIR.glob("*"))
    candidates = [
        path
        for path in current - before
        if path.is_file() and not is_partial_download(path) and is_artifact_download_file(path)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def pending_downloads(before: set[Path]) -> list[Path]:
    current = set(DOWNLOAD_DIR.glob("*"))
    return sorted(
        [path for path in current - before if path.is_file() and is_partial_download(path)],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def wait_for_download_settled(before: set[Path], timeout: int = 90) -> Path | None:
    """Wait until Chrome finishes partial downloads (.crdownload) and an artifact (.opml / .md) appears."""
    deadline = time.time() + timeout
    last_size: dict[str, int] = {}
    last_logged = 0.0

    while time.time() < deadline:
        partial = pending_downloads(before)
        if partial:
            for path in partial:
                size = path.stat().st_size
                key = path.name
                if last_size.get(key) == size and not key.endswith(".crdownload"):
                    continue
                last_size[key] = size
            if time.time() - last_logged > 10:
                log(f"Download in progress: {[p.name for p in partial]}")
                last_logged = time.time()
            time.sleep(1.0)
            continue

        downloaded = newest_download(before)
        if downloaded:
            return downloaded

        candidates = find_artifact_candidates_in_downloads(before)
        if candidates:
            return candidates[0]

        time.sleep(1.0)

    return newest_download(before) or (find_artifact_candidates_in_downloads(before) or [None])[0]


def find_artifact_candidates_in_downloads(before: set[Path]) -> list[Path]:
    """Return newly downloaded files that look like artifacts (.opml / .md) by name or content."""
    current = set(DOWNLOAD_DIR.glob("*"))
    new_files = [p for p in (current - before) if p.is_file() and not p.name.endswith((".crdownload", ".tmp", ".part"))]
    artifact_like = [p for p in new_files if is_artifact_download_file(p)]
    return sorted(artifact_like, key=lambda p: p.stat().st_mtime, reverse=True)


# Back-compat alias
find_opml_candidates_in_downloads = find_artifact_candidates_in_downloads


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


def click_candidate_and_wait(driver: webdriver.Edge, element, before: set[Path]) -> Path | None:
    text, href, title, aria, context = element_download_fields(element)
    if not is_opml_download_trigger(text=text, href=href, title=title, aria=aria, context=context):
        return None

    txt = (text or aria or title or href or "")[:120]
    log(f"Clicking OPML download candidate: {txt!r}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.4)
    driver.execute_script("arguments[0].click();", element)
    deadline = time.time() + 45
    while time.time() < deadline:
        dl = wait_for_download_settled(before, timeout=3)
        if dl:
            log(f"Download detected after click: {dl.name}")
            return dl
        time.sleep(0.8)
    return None


def click_new_download_link(driver: webdriver.Edge, before: set[Path]) -> Path | None:
    """Aggressively hunt for any download trigger related to OPML / files / sandbox attachments.
    Covers the common cases where ChatGPT shows:
      - "Download the OPML mind map" button/link
      - sandbox:/... file links
      - Attachment cards with download icons
    """
    # 1. Prefer candidates inside assistant messages. Global ChatGPT page links
    # include unrelated UI such as "Download apps" and "Get ChatGPT mobile".
    try:
        assistants = driver.find_elements(By.CSS_SELECTOR, "[data-message-author-role='assistant']")
        for assistant in reversed(assistants):
            elements = assistant.find_elements(By.CSS_SELECTOR, "a[href], button, [role='link'], [role='button']")
            for element in reversed(elements):
                try:
                    if not element.is_displayed():
                        continue
                    downloaded = click_candidate_and_wait(driver, element, before)
                    if downloaded:
                        return downloaded
                except Exception:
                    continue
    except Exception:
        pass

    # 2. Page-wide fallback, restricted to explicit OPML/sandbox references.
    download_xpaths = [
        "//a[contains(@href, '.opml')]",
        "//a[contains(@href, 'sandbox:')]",
        "//*[@role='link'][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'opml')]",
        "//a[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'opml')]",
        "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'opml')]",
    ]
    for xpath in download_xpaths:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
        except Exception:
            continue
        for element in reversed(elements):
            try:
                if not element.is_displayed():
                    continue
                downloaded = click_candidate_and_wait(driver, element, before)
                if downloaded:
                    return downloaded
            except Exception:
                continue

    # 3. Broad scan of all <a href>, still filtered against global app links.
    links = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    likely = []
    for link in links:
        try:
            if not link.is_displayed():
                continue
            text, href, title, aria, context = element_download_fields(link)
            if is_opml_download_trigger(text=text, href=href, title=title, aria=aria, context=context):
                likely.append(link)
        except Exception:
            continue

    for link in reversed(likely):
        try:
            downloaded = click_candidate_and_wait(driver, link, before)
            if downloaded:
                return downloaded
        except Exception:
            continue

    # 4. Last-resort: look inside the latest assistant message for any clickable file reference.
    try:
        assistants = driver.find_elements(By.CSS_SELECTOR, "[data-message-author-role='assistant']")
        if assistants:
            last = assistants[-1]
            file_links = last.find_elements(By.CSS_SELECTOR, "a[href]")
            for fl in reversed(file_links):
                try:
                    if fl.is_displayed():
                        text, href, title, aria, context = element_download_fields(fl)
                        if is_opml_download_trigger(text=text, href=href, title=title, aria=aria, context=context):
                            log(f"Clicking file link inside assistant bubble: {href[:80]}")
                            driver.execute_script("arguments[0].click();", fl)
                            time.sleep(5)
                            downloaded = newest_download(before)
                            if downloaded:
                                return downloaded
                except Exception:
                    pass
    except Exception:
        pass

    return None


def wait_and_salvage_download(before: set[Path], timeout: int = 90) -> Path | None:
    """Wait for settled downloads and salvage OPML files that appeared indirectly."""
    deadline = time.time() + timeout
    last_logged = 0.0
    while time.time() < deadline:
        dl = wait_for_download_settled(before, timeout=3)
        if dl:
            return dl
        if time.time() - last_logged > 12:
            partial = pending_downloads(before)
            if partial:
                log(f"Still waiting for download to finish: {[p.name for p in partial]}")
            else:
                log("Still waiting for any new file in downloads/ ...")
            last_logged = time.time()
        time.sleep(1.2)
    candidates = find_opml_candidates_in_downloads(before)
    return candidates[0] if candidates else None


def resolve_download(
    driver: webdriver.Edge | None,
    before: set[Path],
    *,
    timeout: int = 90,
    click: bool = True,
) -> Path | None:
    """Unified download resolution used by batch runners (multi-pass click + salvage)."""
    downloaded = None
    if click and driver is not None:
        downloaded = click_new_download_link(driver, before)
        if downloaded is None:
            log("First download click pass missed; retrying download element scan...")
            time.sleep(2)
            downloaded = click_new_download_link(driver, before)
    if downloaded is None:
        downloaded = wait_and_salvage_download(before, timeout=timeout)
    if downloaded is None:
        candidates = find_opml_candidates_in_downloads(before)
        if candidates:
            downloaded = candidates[0]
            log(f"Salvaged file from downloads/: {downloaded.name}")
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

        before_downloads = set(DOWNLOAD_DIR.glob("*"))
        attach_file(driver, file_path, native_upload=native_upload)
        wait_for_file_upload_complete(driver, file_path)
        log("Sending the exact prompt text with the uploaded file...")
        expected_assistant_count = assistant_message_count(driver) + 1
        send_message(driver, prompt)
        wait_until_idle(driver, min_assistant_count=expected_assistant_count)

        downloaded = click_new_download_link(driver, before_downloads)
        if downloaded is None:
            try:
                downloaded = wait_and_salvage_download(before_downloads, timeout=50)
            except Exception:
                pass

        # Last-chance broad salvage for auto-downloads / sandbox links
        if downloaded is None:
            try:
                cands = find_opml_candidates_in_downloads(before_downloads)
                if cands:
                    downloaded = cands[0]
                    log(f"Salvaged file from downloads/: {downloaded.name}")
            except Exception:
                pass

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
