from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import batch_common as common
import run_chatgpt_temporary_test as core


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "markdown"
DEFAULT_PROMPT = ROOT / "prompts" / "prompt-mind-map.md"


@dataclass(frozen=True)
class MarkdownSection:
    index: int
    title: str
    text: str

    @property
    def output_stem(self) -> str:
        return f"{self.index:02d}_{core.safe_filename(self.title).lower()}"


def batch_log(message: str) -> None:
    common.batch_log(message)


def parse_section_numbers(value: str | None) -> set[int] | None:
    if not value:
        return None

    selected: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start <= 0 or end <= 0 or end < start:
                raise ValueError(f"Invalid section range: {part}")
            selected.update(range(start, end + 1))
        else:
            section = int(part)
            if section <= 0:
                raise ValueError(f"Invalid section number: {part}")
            selected.add(section)
    return selected


def split_markdown_sections(markdown_path: Path) -> list[MarkdownSection]:
    text = markdown_path.read_text(encoding="utf-8")
    heading_pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(heading_pattern.finditer(text))
    sections: list[MarkdownSection] = []

    for zero_index, match in enumerate(matches):
        start = match.start()
        end = matches[zero_index + 1].start() if zero_index + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        section_text = text[start:end].strip()
        if title and section_text:
            sections.append(MarkdownSection(index=len(sections) + 1, title=title, text=section_text))

    return sections


def select_sections(
    sections: list[MarkdownSection],
    sections_filter: set[int] | None,
    limit: int | None,
) -> list[MarkdownSection]:
    if sections_filter is not None:
        sections = [section for section in sections if section.index in sections_filter]
    if limit is not None:
        sections = sections[:limit]
    return sections


def write_markdown_section_file(section: MarkdownSection, section_dir: Path) -> Path:
    section_dir.mkdir(parents=True, exist_ok=True)
    section_path = section_dir / f"{section.output_stem}.md"
    section_path.write_text(section.text.rstrip() + "\n", encoding="utf-8")
    return section_path


def build_section_prompt(prompt: str, section: MarkdownSection) -> str:
    return (
        f"{prompt}\n\n"
        "Use the uploaded Markdown file as the complete source text. "
        f"It contains section {section.index}: {section.title}. "
        "Generate the requested downloadable file from only that uploaded section."
    )


def process_markdown_section(
    driver,
    prompt: str,
    section: MarkdownSection,
    section_file: Path,
    output_dir: Path,
    model: str | None,
    download_timeout: int,
    save_diagnostics: bool,
    output_ext: str = "opml",
) -> bool:
    ext = output_ext.lstrip(".")
    output_path = output_dir / f"{section.output_stem}.{ext}"
    batch_log(f"Processing section {section.index}: {section.title}")

    core.start_new_chat(driver)
    if model:
        core.select_model(driver, model)

    before_downloads = set(core.DOWNLOAD_DIR.glob("*"))
    core.attach_file(driver, section_file, native_upload=False)
    core.wait_for_file_upload_complete(driver, section_file)

    expected_assistant_count = core.assistant_message_count(driver) + 1
    core.send_message(driver, build_section_prompt(prompt, section))
    core.wait_until_idle(driver, min_assistant_count=expected_assistant_count)

    downloaded = core.resolve_download(driver, before_downloads, timeout=download_timeout)

    if save_diagnostics:
        response_text = core.latest_assistant_text(driver)
        (output_dir / f"{section.output_stem}.last_response.txt").write_text(
            response_text,
            encoding="utf-8",
        )
        driver.save_screenshot(str(output_dir / f"{section.output_stem}.last_state.png"))

    if downloaded is None:
        batch_log(f"FAILED: no downloadable {ext.upper()} detected for section {section.index}: {section.title}")
        return False

    common.save_artifact_download(downloaded, output_path)
    batch_log(f"Saved {ext.upper()}: {output_path}")
    return True


def run_batch(
    markdown_file: Path,
    output_dir: Path,
    prompt_path: Path,
    sections_filter: set[int] | None = None,
    overwrite: bool = False,
    limit: int | None = None,
    model: str | None = None,
    save_diagnostics: bool = False,
    max_section_attempts: int = 3,
    download_timeout: int = 90,
    close_delay: int = 20,
    chrome_profile_dir: Path | None = None,
    skip_warmup: bool = False,
    keep_browser: bool = False,
    output_ext: str = "opml",
) -> int:
    core.LOG_FILE.write_text("", encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    if chrome_profile_dir is not None:
        os.environ["CHATGPT_CHROME_PROFILE_DIR"] = str(chrome_profile_dir)

    if not markdown_file.exists():
        raise FileNotFoundError(markdown_file)
    if not prompt_path.exists():
        raise FileNotFoundError(prompt_path)

    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Prompt file is empty.")

    all_sections = split_markdown_sections(markdown_file)
    sections = select_sections(all_sections, sections_filter, limit)
    if not sections:
        batch_log(f"No matching level-2 Markdown sections found in {markdown_file}")
        return 1

    section_dir = output_dir / "_md_sections"
    ext = output_ext.lstrip(".")
    batch_log(f"Markdown file: {markdown_file}")
    batch_log(f"Output folder: {output_dir}")
    batch_log(f"Output extension: .{ext}")
    batch_log(f"Detected sections: {len(all_sections)}")
    batch_log(f"Sections to process: {len(sections)}")

    driver = common.bootstrap_session(model, skip_warmup=skip_warmup)
    successes = 0
    failures: list[str] = []
    try:
        for position, section in enumerate(sections, start=1):
            output_path = output_dir / f"{section.output_stem}.{ext}"
            if output_path.exists() and not overwrite:
                batch_log(f"Skipping existing ({position}/{len(sections)}): {output_path.name}")
                successes += 1
                continue

            batch_log(f"Starting section {section.index} ({position}/{len(sections)})")
            section_file = write_markdown_section_file(section, section_dir)

            def attempt(driver_obj):
                return process_markdown_section(
                    driver=driver_obj,
                    prompt=prompt,
                    section=section,
                    section_file=section_file,
                    output_dir=output_dir,
                    model=model,
                    download_timeout=download_timeout,
                    save_diagnostics=save_diagnostics,
                    output_ext=output_ext,
                )

            label = f"section {section.index:02d} {section.title}"
            ok, driver = common.run_with_retries(
                label,
                driver,
                model,
                attempt,
                max_attempts=max_section_attempts,
                skip_warmup=skip_warmup,
            )
            if ok:
                successes += 1
            else:
                failures.append(f"{section.index:02d} {section.title}")
            common.prune_driver_cookies(driver)

        batch_log(f"Markdown batch complete. Successes: {successes}. Failures: {len(failures)}.")
        if failures:
            batch_log("Failed sections:")
            for name in failures:
                batch_log(f"- {name}")

        common.write_batch_summary(
            mode=f"markdown-{ext}",
            successes=successes,
            failures=failures,
            output_dir=output_dir,
            extra={
                "markdown_file": str(markdown_file),
                "max_section_attempts": max_section_attempts,
                "download_timeout": download_timeout,
                "output_ext": ext,
            },
        )
        return 0 if not failures else 2
    finally:
        if keep_browser:
            batch_log("Keeping browser open (--keep-browser).")
        else:
            batch_log(f"Closing browser in {close_delay} seconds...")
            time.sleep(close_delay)
            common.quit_driver(driver)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Process each ## section in a Markdown file with a prompt and download the generated artifact (OPML or Markdown).")
    parser.add_argument("--markdown-file", type=Path, required=True, help="Markdown file with ## section headings")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--sections", default=None, help="Comma-separated section numbers or ranges, e.g. 20,21,22 or 20-22.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--model", default=None)
    parser.add_argument("--save-diagnostics", action="store_true")
    parser.add_argument("--max-section-attempts", type=int, default=3)
    parser.add_argument("--download-timeout", type=int, default=90)
    parser.add_argument("--close-delay", type=int, default=20)
    parser.add_argument("--chrome-profile-dir", type=Path, default=None)
    parser.add_argument("--output-ext", default="opml", help="Output file extension (opml or md)")
    parser.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Skip the initial hello warm-up message when opening ChatGPT.",
    )
    parser.add_argument(
        "--keep-browser",
        action="store_true",
        help="Do not close the browser when the batch finishes.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return run_batch(
            markdown_file=args.markdown_file,
            output_dir=args.output_dir,
            prompt_path=args.prompt,
            sections_filter=parse_section_numbers(args.sections),
            overwrite=args.overwrite,
            limit=args.limit,
            model=args.model,
            save_diagnostics=args.save_diagnostics,
            output_ext=getattr(args, "output_ext", "opml"),
            max_section_attempts=args.max_section_attempts,
            download_timeout=args.download_timeout,
            close_delay=args.close_delay,
            chrome_profile_dir=args.chrome_profile_dir,
            skip_warmup=args.no_warm_up,
            keep_browser=args.keep_browser,
        )
    except Exception as exc:
        core.log(f"ERROR: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
