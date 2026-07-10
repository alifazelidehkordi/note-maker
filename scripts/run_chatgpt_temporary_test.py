"""Legacy API facade for the Selenium browser implementation.

New batch code consumes :mod:`browser_runtime` contracts. This module preserves
all Phase-0 entry points while delegating implementation to the internal
``browser_runtime.selenium_legacy`` module. Runtime globals and patched helper
functions are synchronized before each call, preserving existing extension and
test seams during the migration.
"""
from __future__ import annotations

from functools import wraps
import time
from browser_runtime import selenium_legacy as _legacy

ROOT = _legacy.ROOT
DEFAULT_PROMPT = _legacy.DEFAULT_PROMPT
CHROME_CANDIDATES = _legacy.CHROME_CANDIDATES
EDGE_CANDIDATES = _legacy.EDGE_CANDIDATES
CHROME_NAMES = _legacy.CHROME_NAMES
EDGE_NAMES = _legacy.EDGE_NAMES
CHROME_PROFILE_DIR = _legacy.CHROME_PROFILE_DIR
EDGE_PROFILE_DIR = _legacy.EDGE_PROFILE_DIR
DOWNLOAD_DIR = _legacy.DOWNLOAD_DIR
TEXT_OUTPUT = _legacy.TEXT_OUTPUT
SCREENSHOT = _legacy.SCREENSHOT
LOG_FILE = _legacy.LOG_FILE
CHATGPT_URL = _legacy.CHATGPT_URL
SEND_SELECTORS = _legacy.SEND_SELECTORS
DownloadSnapshot = _legacy.DownloadSnapshot

_PUBLIC_FUNCTIONS = (
    'find_browser_binary', 'pyautogui_module', 'paste_hotkey', 'build_driver',
    'wait_for_editor', 'dismiss_cookie_banner', 'login_buttons_visible',
    'visible_body_text', 'page_has_load_error', 'reload_and_wait_for_editor',
    'wait_until_logged_in', 'start_new_chat', 'select_model', 'set_editor_text',
    'editor_text', 'find_enabled_send_button', 'wait_for_send_enabled',
    'click_send', 'send_message', 'assistant_message_count', 'wait_until_idle',
    'wait_until_editor_ready', 'click_attach_menu', 'native_attach_file',
    'dom_attach_file', 'attach_file', 'upload_pending_visible',
    'wait_for_file_upload_complete', 'normalize_expected_extensions',
    'accepted_artifact_suffixes', 'is_partial_download', 'snapshot_downloads',
    'is_artifact_download_file', 'is_opml_download_file',
    'is_artifact_download_trigger', 'is_opml_download_trigger',
    'newest_download', 'pending_downloads', 'wait_for_download_settled',
    'find_artifact_candidates_in_downloads', 'find_opml_candidates_in_downloads',
    'element_download_fields', 'click_candidate_and_wait',
    'click_new_download_link', 'wait_and_salvage_download', 'resolve_download',
    'latest_assistant_text', 'safe_filename', 'run', 'main',
)
_ORIGINALS = {name: getattr(_legacy, name) for name in _PUBLIC_FUNCTIONS}


def log(message: str) -> None:
    print(message, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open('a', encoding='utf-8') as handle:
        handle.write(message + '\n')


def _sync_legacy_namespace() -> None:
    for name in (
        'ROOT', 'DEFAULT_PROMPT', 'CHROME_CANDIDATES', 'EDGE_CANDIDATES',
        'CHROME_NAMES', 'EDGE_NAMES', 'CHROME_PROFILE_DIR', 'EDGE_PROFILE_DIR',
        'DOWNLOAD_DIR', 'TEXT_OUTPUT', 'SCREENSHOT', 'LOG_FILE', 'CHATGPT_URL',
        'SEND_SELECTORS',
    ):
        setattr(_legacy, name, globals()[name])
    _legacy.log = log
    # Preserve monkey-patch and plugin seams used by legacy callers. The target
    # implementation is invoked from _ORIGINALS, so assigning wrappers here does
    # not recurse.
    for name in _PUBLIC_FUNCTIONS:
        setattr(_legacy, name, globals()[name])


def _delegate_call(name: str, *args, **kwargs):
    _sync_legacy_namespace()
    return _ORIGINALS[name](*args, **kwargs)


@wraps(_ORIGINALS['find_browser_binary'])
def find_browser_binary(*args, **kwargs):
    return _delegate_call('find_browser_binary', *args, **kwargs)


@wraps(_ORIGINALS['pyautogui_module'])
def pyautogui_module(*args, **kwargs):
    return _delegate_call('pyautogui_module', *args, **kwargs)


@wraps(_ORIGINALS['paste_hotkey'])
def paste_hotkey(*args, **kwargs):
    return _delegate_call('paste_hotkey', *args, **kwargs)


@wraps(_ORIGINALS['build_driver'])
def build_driver(*args, **kwargs):
    return _delegate_call('build_driver', *args, **kwargs)


def _build_driver_with_paths(*args, **kwargs):
    """Private provider hook that preserves managed profile/download paths."""
    _sync_legacy_namespace()
    return _legacy._build_driver_with_paths(*args, **kwargs)


@wraps(_ORIGINALS['wait_for_editor'])
def wait_for_editor(*args, **kwargs):
    return _delegate_call('wait_for_editor', *args, **kwargs)


@wraps(_ORIGINALS['dismiss_cookie_banner'])
def dismiss_cookie_banner(*args, **kwargs):
    return _delegate_call('dismiss_cookie_banner', *args, **kwargs)


@wraps(_ORIGINALS['login_buttons_visible'])
def login_buttons_visible(*args, **kwargs):
    return _delegate_call('login_buttons_visible', *args, **kwargs)


@wraps(_ORIGINALS['visible_body_text'])
def visible_body_text(*args, **kwargs):
    return _delegate_call('visible_body_text', *args, **kwargs)


@wraps(_ORIGINALS['page_has_load_error'])
def page_has_load_error(*args, **kwargs):
    return _delegate_call('page_has_load_error', *args, **kwargs)


@wraps(_ORIGINALS['reload_and_wait_for_editor'])
def reload_and_wait_for_editor(*args, **kwargs):
    return _delegate_call('reload_and_wait_for_editor', *args, **kwargs)


@wraps(_ORIGINALS['wait_until_logged_in'])
def wait_until_logged_in(*args, **kwargs):
    return _delegate_call('wait_until_logged_in', *args, **kwargs)


@wraps(_ORIGINALS['start_new_chat'])
def start_new_chat(*args, **kwargs):
    return _delegate_call('start_new_chat', *args, **kwargs)


@wraps(_ORIGINALS['select_model'])
def select_model(*args, **kwargs):
    return _delegate_call('select_model', *args, **kwargs)


@wraps(_ORIGINALS['set_editor_text'])
def set_editor_text(*args, **kwargs):
    return _delegate_call('set_editor_text', *args, **kwargs)


@wraps(_ORIGINALS['editor_text'])
def editor_text(*args, **kwargs):
    return _delegate_call('editor_text', *args, **kwargs)


@wraps(_ORIGINALS['find_enabled_send_button'])
def find_enabled_send_button(*args, **kwargs):
    return _delegate_call('find_enabled_send_button', *args, **kwargs)


@wraps(_ORIGINALS['wait_for_send_enabled'])
def wait_for_send_enabled(*args, **kwargs):
    return _delegate_call('wait_for_send_enabled', *args, **kwargs)


@wraps(_ORIGINALS['click_send'])
def click_send(*args, **kwargs):
    return _delegate_call('click_send', *args, **kwargs)


@wraps(_ORIGINALS['send_message'])
def send_message(*args, **kwargs):
    return _delegate_call('send_message', *args, **kwargs)


@wraps(_ORIGINALS['assistant_message_count'])
def assistant_message_count(*args, **kwargs):
    return _delegate_call('assistant_message_count', *args, **kwargs)


@wraps(_ORIGINALS['wait_until_idle'])
def wait_until_idle(*args, **kwargs):
    return _delegate_call('wait_until_idle', *args, **kwargs)


@wraps(_ORIGINALS['wait_until_editor_ready'])
def wait_until_editor_ready(*args, **kwargs):
    return _delegate_call('wait_until_editor_ready', *args, **kwargs)


@wraps(_ORIGINALS['click_attach_menu'])
def click_attach_menu(*args, **kwargs):
    return _delegate_call('click_attach_menu', *args, **kwargs)


@wraps(_ORIGINALS['native_attach_file'])
def native_attach_file(*args, **kwargs):
    return _delegate_call('native_attach_file', *args, **kwargs)


@wraps(_ORIGINALS['dom_attach_file'])
def dom_attach_file(*args, **kwargs):
    return _delegate_call('dom_attach_file', *args, **kwargs)


@wraps(_ORIGINALS['attach_file'])
def attach_file(*args, **kwargs):
    return _delegate_call('attach_file', *args, **kwargs)


@wraps(_ORIGINALS['upload_pending_visible'])
def upload_pending_visible(*args, **kwargs):
    return _delegate_call('upload_pending_visible', *args, **kwargs)


@wraps(_ORIGINALS['wait_for_file_upload_complete'])
def wait_for_file_upload_complete(*args, **kwargs):
    return _delegate_call('wait_for_file_upload_complete', *args, **kwargs)


@wraps(_ORIGINALS['normalize_expected_extensions'])
def normalize_expected_extensions(*args, **kwargs):
    return _delegate_call('normalize_expected_extensions', *args, **kwargs)


@wraps(_ORIGINALS['accepted_artifact_suffixes'])
def accepted_artifact_suffixes(*args, **kwargs):
    return _delegate_call('accepted_artifact_suffixes', *args, **kwargs)


@wraps(_ORIGINALS['is_partial_download'])
def is_partial_download(*args, **kwargs):
    return _delegate_call('is_partial_download', *args, **kwargs)


@wraps(_ORIGINALS['snapshot_downloads'])
def snapshot_downloads(*args, **kwargs):
    return _delegate_call('snapshot_downloads', *args, **kwargs)


@wraps(_ORIGINALS['is_artifact_download_file'])
def is_artifact_download_file(*args, **kwargs):
    return _delegate_call('is_artifact_download_file', *args, **kwargs)


@wraps(_ORIGINALS['is_opml_download_file'])
def is_opml_download_file(*args, **kwargs):
    return _delegate_call('is_opml_download_file', *args, **kwargs)


@wraps(_ORIGINALS['is_artifact_download_trigger'])
def is_artifact_download_trigger(*args, **kwargs):
    return _delegate_call('is_artifact_download_trigger', *args, **kwargs)


@wraps(_ORIGINALS['is_opml_download_trigger'])
def is_opml_download_trigger(*args, **kwargs):
    return _delegate_call('is_opml_download_trigger', *args, **kwargs)


@wraps(_ORIGINALS['newest_download'])
def newest_download(*args, **kwargs):
    return _delegate_call('newest_download', *args, **kwargs)


@wraps(_ORIGINALS['pending_downloads'])
def pending_downloads(*args, **kwargs):
    return _delegate_call('pending_downloads', *args, **kwargs)


@wraps(_ORIGINALS['wait_for_download_settled'])
def wait_for_download_settled(*args, **kwargs):
    return _delegate_call('wait_for_download_settled', *args, **kwargs)


@wraps(_ORIGINALS['find_artifact_candidates_in_downloads'])
def find_artifact_candidates_in_downloads(*args, **kwargs):
    return _delegate_call('find_artifact_candidates_in_downloads', *args, **kwargs)


@wraps(_ORIGINALS['find_opml_candidates_in_downloads'])
def find_opml_candidates_in_downloads(*args, **kwargs):
    return _delegate_call('find_opml_candidates_in_downloads', *args, **kwargs)


@wraps(_ORIGINALS['element_download_fields'])
def element_download_fields(*args, **kwargs):
    return _delegate_call('element_download_fields', *args, **kwargs)


@wraps(_ORIGINALS['click_candidate_and_wait'])
def click_candidate_and_wait(
    driver,
    element,
    before,
    *,
    expected_extensions,
    started_at_ns,
):
    """Click an artifact card and handle ChatGPT's preview download UI."""
    _sync_legacy_namespace()
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

    label = (text or aria or title or href or '')[:120]
    log(f"Clicking artifact download candidate: {label!r}")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    time.sleep(0.4)
    driver.execute_script("arguments[0].click();", element)

    # Generated files may open in a preview. In that case the card is only the
    # first click and the preview header's Download button starts the real save.
    preview_deadline = time.time() + 5
    while time.time() < preview_deadline:
        preview_buttons = []
        for selector in (
            "button[aria-label='Download' i]",
            "button[title='Download' i]",
            "button[data-testid='download' i]",
            "[role='button'][aria-label='Download' i]",
            "[role='button'][title='Download' i]",
        ):
            try:
                preview_buttons.extend(
                    driver.find_elements(_legacy.By.CSS_SELECTOR, selector)
                )
            except Exception:
                continue
        for button in reversed(preview_buttons):
            try:
                if not button.is_displayed() or button == element:
                    continue
                button_label = (
                    button.get_attribute('aria-label')
                    or button.get_attribute('title')
                    or button.text
                    or 'Download'
                )
                if button_label.strip().lower() != 'download':
                    continue
                log(f"Clicking artifact preview download button: {button_label!r}")
                driver.execute_script("arguments[0].click();", button)
                preview_deadline = 0
                break
            except Exception:
                continue
        if preview_deadline == 0:
            break
        time.sleep(0.25)

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


@wraps(_ORIGINALS['click_new_download_link'])
def click_new_download_link(*args, **kwargs):
    return _delegate_call('click_new_download_link', *args, **kwargs)


@wraps(_ORIGINALS['wait_and_salvage_download'])
def wait_and_salvage_download(*args, **kwargs):
    return _delegate_call('wait_and_salvage_download', *args, **kwargs)


@wraps(_ORIGINALS['resolve_download'])
def resolve_download(*args, **kwargs):
    return _delegate_call('resolve_download', *args, **kwargs)


@wraps(_ORIGINALS['latest_assistant_text'])
def latest_assistant_text(*args, **kwargs):
    return _delegate_call('latest_assistant_text', *args, **kwargs)


@wraps(_ORIGINALS['safe_filename'])
def safe_filename(*args, **kwargs):
    return _delegate_call('safe_filename', *args, **kwargs)


@wraps(_ORIGINALS['run'])
def run(*args, **kwargs):
    return _delegate_call('run', *args, **kwargs)


@wraps(_ORIGINALS['main'])
def main(*args, **kwargs):
    return _delegate_call('main', *args, **kwargs)

if __name__ == '__main__':
    raise SystemExit(main())
