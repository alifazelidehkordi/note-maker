from __future__ import annotations

"""Central selector and UI-text registry for browser providers.

Selectors are intentionally ordered from the most stable/test-id based option to
broader fallbacks. Batch modules must never import this module directly.
"""

CHATGPT_URL = "https://chatgpt.com/?temporary-chat=true"

EDITOR_SELECTORS = (
    "#prompt-textarea",
    "div[contenteditable='true'][data-placeholder]",
    "div[contenteditable='true'][role='textbox']",
    "textarea",
)

SEND_BUTTON_SELECTORS = (
    "button[data-testid='send-button']",
    "button[data-testid='composer-submit-button']",
    "button[aria-label*='Send']",
    "button[aria-label*='ارسال']",
)

STOP_BUTTON_SELECTORS = (
    "button[data-testid='stop-button']",
    "button[aria-label*='Stop']",
    "button[aria-label*='stop']",
)

ATTACH_BUTTON_SELECTORS = (
    "button[data-testid='composer-plus-btn']",
    "button[aria-label*='Attach']",
    "button[aria-label*='Upload']",
    "button[aria-label*='پیوست']",
)

MODEL_BUTTON_SELECTORS = (
    "button[data-testid='model-switcher-dropdown-button']",
    "button[aria-label*='model']",
    "button:has-text('GPT')",
)

FILE_INPUT_SELECTOR = "input[type='file']"
ASSISTANT_MESSAGE_SELECTOR = "[data-message-author-role='assistant']"
DOWNLOAD_CANDIDATE_SELECTOR = "a[href], button, [role='link'], [role='button']"
RATE_LIMIT_MODAL_SELECTOR = "#modal-conversation-history-rate-limit"
UPLOAD_PROGRESS_SELECTORS = (
    "[data-testid='file-upload-progress']",
    "[aria-label*='uploading']",
    "[aria-label*='Uploading']",
)
UPLOAD_ERROR_SELECTORS = (
    "[data-testid='file-upload-error']",
    "[role='alert']",
)

COOKIE_BUTTON_LABELS = (
    "Accept all",
    "Reject non-essential",
    "Allow all",
)

LOGIN_BUTTON_PATTERN = r"Log in|Sign up|ورود|ثبت نام"

CLOUDFLARE_PHRASES = (
    "verify you are human",
    "checking your browser",
    "just a moment",
    "performing security verification",
)

RATE_LIMIT_PHRASES = (
    "too many requests",
    "you've reached our limit",
    "you have reached the limit",
    "rate limit",
    "try again later",
)

NETWORK_ERROR_MARKERS = (
    "internet_disconnected",
    "net::err_internet_disconnected",
    "net::err_name_not_resolved",
    "net::err_connection_refused",
    "net::err_connection_reset",
    "net::err_timed_out",
    "network",
    "enotfound",
    "econnrefused",
    "offline",
    "name not resolved",
    "connection reset",
)

NON_FILE_DOWNLOAD_PHRASES = (
    "download apps",
    "get chatgpt mobile",
    "chatgpt mobile",
    "app store",
    "google play",
)
