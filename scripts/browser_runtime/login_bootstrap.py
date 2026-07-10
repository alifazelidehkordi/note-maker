from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import BrowserConfigurationError, ProfileSnapshotError
from .profile_manager import ProfileManager, ProfileSnapshot

CHATGPT_URL = "https://chatgpt.com/?temporary-chat=true"


def find_chromium_binary() -> Path | None:
    override = os.environ.get("CHATGPT_CHROME_BINARY", "").strip()
    candidates = [override] if override else []
    candidates.extend(
        [
            "google-chrome-stable",
            "google-chrome",
            "chromium-browser",
            "chromium",
            "microsoft-edge-stable",
            "msedge",
        ]
    )
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.is_file():
            return path.resolve()
        found = shutil.which(candidate)
        if found:
            return Path(found).resolve()
    return None


class LoginBootstrapper:
    """Creates a reusable login profile with a real Chromium process."""

    def __init__(self, *, profile_manager: ProfileManager) -> None:
        self.profile_manager = profile_manager

    def open_login_browser(
        self,
        profile_dir: Path,
        *,
        url: str = CHATGPT_URL,
        wait: bool = True,
    ) -> subprocess.Popen[bytes]:
        binary = find_chromium_binary()
        if binary is None:
            raise BrowserConfigurationError(
                "Chrome/Chromium was not found. Install it or set CHATGPT_CHROME_BINARY."
            )
        profile_dir = Path(profile_dir).expanduser().resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_manager.assert_profile_inactive(profile_dir)
        command = [
            str(binary),
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
        process = subprocess.Popen(command)
        if wait:
            process.wait()
        return process

    def create_snapshot(
        self,
        profile_dir: Path,
        *,
        name: str = "default",
    ) -> ProfileSnapshot:
        evidence = self.profile_manager.inspect_auth_session(profile_dir)
        if not evidence.authenticated:
            raise ProfileSnapshotError(
                "The reference profile does not contain a reusable ChatGPT login session. "
                "Open the login browser, finish login, close it, and retry."
            )
        return self.profile_manager.create_snapshot(
            profile_dir,
            name=name,
            require_auth=True,
        )
