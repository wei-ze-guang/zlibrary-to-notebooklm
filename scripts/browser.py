from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrowserLaunchChoice:
    options: dict[str, Any]
    log: str | None = None


SYSTEM_BROWSER_CHANNELS: tuple[tuple[str, Path, str], ...] = (
    (
        "chrome",
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        "系统 Chrome",
    ),
    (
        "msedge",
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        "系统 Microsoft Edge",
    ),
)


def choose_system_browser_channel() -> tuple[str, str] | None:
    for channel, browser_path, label in SYSTEM_BROWSER_CHANNELS:
        if browser_path.exists():
            return channel, label
    return None


def choose_chromium_launch_options(chromium: Any) -> BrowserLaunchChoice:
    executable_path = Path(chromium.executable_path)
    if executable_path.exists():
        return BrowserLaunchChoice(options={})

    browser_channel = choose_system_browser_channel()
    if browser_channel:
        channel, label = browser_channel
        return BrowserLaunchChoice(
            options={"channel": channel},
            log=f"Playwright 自带 Chromium 未找到，已改用{label}打开浏览器",
        )

    raise RuntimeError("没有找到 Playwright Chromium 或系统 Chrome，请运行 playwright install chromium")
