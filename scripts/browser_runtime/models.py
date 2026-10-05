from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

DownloadSnapshot = dict[Path, tuple[int, int] | None]


def normalize_extensions(values: set[str] | frozenset[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        item = str(value).strip().lower()
        if not item:
            continue
        normalized.add(item if item.startswith('.') else f'.{item}')
    if not normalized:
        raise ValueError('At least one expected extension is required.')
    return frozenset(normalized)


class BrowserHealthStatus(str, Enum):
    HEALTHY = 'healthy'
    DEGRADED = 'degraded'
    DEAD = 'dead'


@dataclass(frozen=True)
class BrowserHealth:
    status: BrowserHealthStatus
    detail: str = ''
    current_url: str | None = None

    @property
    def healthy(self) -> bool:
        return self.status is BrowserHealthStatus.HEALTHY


@dataclass(frozen=True)
class BrowserLaunchOptions:
    browser: str = 'chrome'
    headless: bool = False
    width: int = 1400
    height: int = 950
    url: str | None = None
    profile_dir: Path | None = None
    download_dir: Path | None = None
    navigation_timeout: int = 60
    action_timeout: int = 30
    network_recovery_timeout: int = 120
    use_stealth: bool = True

    def __post_init__(self) -> None:
        if self.width < 320 or self.height < 240:
            raise ValueError('Browser window size is too small.')
        for name in ('navigation_timeout', 'action_timeout', 'network_recovery_timeout'):
            if getattr(self, name) < 1:
                raise ValueError(f'{name} must be at least 1 second.')
        if self.profile_dir is not None:
            object.__setattr__(self, 'profile_dir', Path(self.profile_dir).expanduser().resolve())
        if self.download_dir is not None:
            object.__setattr__(self, 'download_dir', Path(self.download_dir).expanduser().resolve())


@dataclass(frozen=True)
class UploadRequest:
    file_path: Path
    native_upload: bool = False
    timeout: int = 600

    def __post_init__(self) -> None:
        object.__setattr__(self, 'file_path', Path(self.file_path).resolve())
        if self.timeout < 1:
            raise ValueError('Upload timeout must be at least 1 second.')


@dataclass(frozen=True)
class ResponseWaitRequest:
    min_assistant_count: int | None = None
    timeout: int = 600

    def __post_init__(self) -> None:
        if self.timeout < 1:
            raise ValueError('Response timeout must be at least 1 second.')


@dataclass(frozen=True)
class DownloadRequest:
    before: Any
    expected_extensions: frozenset[str] | set[str]
    started_at_ns: int
    timeout: int = 90
    click: bool = True
    job_key: str | None = None
    destination_dir: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'expected_extensions', normalize_extensions(self.expected_extensions))
        if self.started_at_ns < 0:
            raise ValueError('started_at_ns cannot be negative.')
        if self.timeout < 1:
            raise ValueError('Download timeout must be at least 1 second.')
        if self.destination_dir is not None:
            object.__setattr__(
                self,
                'destination_dir',
                Path(self.destination_dir).expanduser().resolve(),
            )


@dataclass(frozen=True)
class BrowserOperationRecord:
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
