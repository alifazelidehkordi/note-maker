#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser_runtime import (  # noqa: E402
    BrowserLaunchOptions,
    DownloadRequest,
    PatchrightProvider,
    ResponseWaitRequest,
    UploadRequest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independent Patchright smoke test for Note Maker browser runtime."
    )
    parser.add_argument("--profile-dir", type=Path, default=ROOT / "patchright_profile")
    parser.add_argument("--download-dir", type=Path, default=ROOT / "downloads" / "smoke")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--url", default="https://example.com")
    parser.add_argument("--chatgpt", action="store_true", help="Run the full manual ChatGPT workflow.")
    parser.add_argument("--input", type=Path, help="Artifact to upload in --chatgpt mode.")
    parser.add_argument("--prompt", type=Path, help="Prompt text file in --chatgpt mode.")
    parser.add_argument("--expected-extension", default=".md")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    provider = PatchrightProvider()
    target_url = "https://chatgpt.com/?temporary-chat=true" if args.chatgpt else args.url
    session = provider.open_session(
        BrowserLaunchOptions(
            headless=args.headless,
            profile_dir=args.profile_dir,
            download_dir=args.download_dir,
            url=target_url,
        )
    )
    try:
        print(f"provider={session.provider_name}")
        print(f"profile={session.profile_dir}")
        print(f"downloads={session.download_dir}")
        print(f"health={session.health().status.value}")
        if not args.chatgpt:
            if args.url == "about:blank":
                session.raw_handle.set_content(
                    "<!doctype html><title>Patchright Smoke</title><h1>healthy</h1>"
                )
            title = session.raw_handle.title()
            if args.url == "about:blank" and title != "Patchright Smoke":
                raise RuntimeError(f"Unexpected smoke-test title: {title!r}")
            screenshot = args.download_dir / "patchright-basic-smoke.png"
            session.save_screenshot(screenshot)
            print(f"title={title}")
            print(f"basic navigation succeeded; screenshot={screenshot}")
            return 0

        if args.input is None or args.prompt is None:
            raise SystemExit("--chatgpt requires both --input and --prompt")
        if not args.input.exists() or not args.prompt.exists():
            raise FileNotFoundError("Smoke-test input or prompt file does not exist.")

        session.wait_until_logged_in(timeout=args.timeout)
        session.start_new_chat()
        session.select_model(args.model)
        before = session.snapshot_downloads()
        session.upload(UploadRequest(args.input, timeout=args.timeout))
        expected_count = session.assistant_message_count() + 1
        started_at_ns = time.time_ns()
        session.send_message(args.prompt.read_text(encoding="utf-8").strip())
        session.wait_for_response(
            ResponseWaitRequest(
                min_assistant_count=expected_count,
                timeout=args.timeout,
            )
        )
        downloaded = session.resolve_download(
            DownloadRequest(
                before=before,
                expected_extensions={args.expected_extension},
                started_at_ns=started_at_ns,
                timeout=min(args.timeout, 180),
                job_key="manual-smoke",
            )
        )
        if downloaded is None:
            print("FAILED: no matching download was resolved.")
            return 2
        print(f"download={downloaded}")
        print(f"latest_response_chars={len(session.latest_assistant_text())}")
        print("Patchright ChatGPT smoke test passed.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
