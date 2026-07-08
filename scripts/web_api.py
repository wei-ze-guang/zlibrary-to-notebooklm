#!/usr/bin/env python3
"""
Local web API for the Z-Library to NotebookLM workbench.
"""

from __future__ import annotations

import asyncio
import argparse
import contextlib
import io
import json
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.search import build_search_url, extract_search_results, is_networkidle_timeout, search_zlibrary
from scripts.upload import ZLibraryAutoUploader
from scripts.browser import choose_chromium_launch_options, choose_system_browser_channel


WEB_DIST_DIR = ROOT_DIR / "web" / "dist"
WEB_PUBLIC_DIR = ROOT_DIR / "web"
WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "zlibrary-to-notebooklm" / "tasks"
ZLIBRARY_LOGIN_TIMEOUT_SECONDS = 15 * 60
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 80
TASKS: dict[str, "UploadTask"] = {}
TASKS_LOCK = threading.Lock()
TASK_OPERATION_LOCKS: dict[str, threading.Lock] = {}
ZLIBRARY_LOGIN_LOCK = threading.RLock()
ZLIBRARY_LOGIN_SESSION: "ZLibraryLoginSession | None" = None
NOTEBOOKLM_LOGIN_LOCK = threading.RLock()
NOTEBOOKLM_LOGIN_PROCESS: subprocess.Popen[str] | None = None
NOTEBOOKLM_STATUS_CACHE_LOCK = threading.Lock()
NOTEBOOKLM_STATUS_CACHE: dict[str, Any] | None = None
MANAGED_BROWSER_IDLE_TIMEOUT_SECONDS = 15 * 60


class BadRequest(ValueError):
    pass


def sync_playwright_factory():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


class ManagedBrowserSession:
    def __init__(self, idle_timeout_seconds: int = MANAGED_BROWSER_IDLE_TIMEOUT_SECONDS):
        self.idle_timeout_seconds = idle_timeout_seconds
        self.status = "stopped"
        self.message = "浏览器未启动"
        self.error: str | None = None
        self.headless = True
        self.keep_open = True
        self.started_at: float | None = None
        self.updated_at = time.time()
        self.last_used_at: float | None = None
        self.active_operations = 0
        self._lock = threading.RLock()
        self._commands: "queue.Queue[dict[str, Any]] | None" = None
        self._worker: threading.Thread | None = None

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            self._close_if_idle_locked()
            return {
                "status": self.status,
                "message": self.message,
                "error": self.error,
                "headless": self.headless,
                "keep_open": self.keep_open,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "last_used_at": self.last_used_at,
                "active_operations": self.active_operations,
                "idle_timeout_seconds": self.idle_timeout_seconds,
            }

    def start(self, headless: bool = True, keep_open: bool = True, idle_timeout_seconds: int | None = None) -> dict[str, Any]:
        with self._lock:
            self._close_if_idle_locked()
            if self.status in {"running", "busy"} and self._worker and self._worker.is_alive():
                self.keep_open = keep_open
                self.headless = headless
                if idle_timeout_seconds is not None:
                    self.idle_timeout_seconds = idle_timeout_seconds
                self._touch_locked("浏览器已运行")
                return self.serialize()

            start_result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
            self._commands = queue.Queue()
            self.status = "starting"
            self.message = "正在启动浏览器"
            self.error = None
            self.headless = headless
            self.keep_open = keep_open
            if idle_timeout_seconds is not None:
                self.idle_timeout_seconds = idle_timeout_seconds
            self.updated_at = time.time()

            self._worker = threading.Thread(
                target=self._worker_main,
                args=(headless, start_result, self._commands),
                daemon=True,
            )
            self._worker.start()

        try:
            state, payload = start_result.get(timeout=30)
        except queue.Empty:
            with self._lock:
                self.status = "crashed"
                self.error = "浏览器启动超时"
                self.message = "浏览器启动超时"
                self.updated_at = time.time()
            return self.serialize()

        with self._lock:
            if state == "error":
                self.status = "crashed"
                self.error = payload
                self.message = f"浏览器启动失败: {payload}"
                self.updated_at = time.time()
            return self.serialize()

    def close(self, force: bool = False, reason: str = "浏览器已关闭") -> dict[str, Any]:
        with self._lock:
            if self.active_operations and not force:
                raise BadRequest("浏览器正在使用中，请等待任务结束或强制关闭")
            commands = self._commands
            worker = self._worker
            if commands is None or worker is None or not worker.is_alive():
                self._mark_closed_locked(reason)
                return self.serialize()
            result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
            commands.put({"type": "close", "reason": reason, "result": result})

        try:
            result.get(timeout=5)
        except queue.Empty:
            pass

        with self._lock:
            self._mark_closed_locked(reason)
            return self.serialize()

    def _mark_closed_locked(self, reason: str) -> None:
        self._commands = None
        self._worker = None
        self.status = "stopped" if reason != "idle_timeout" else "idle_timeout"
        self.message = "浏览器已因空闲超时关闭" if reason == "idle_timeout" else reason
        self.error = None
        self.updated_at = time.time()

    def restart(self, headless: bool = True, keep_open: bool = True) -> dict[str, Any]:
        self.close(force=True, reason="浏览器正在重启")
        return self.start(headless=headless, keep_open=keep_open)

    def run_with_page(self, callback, headless: bool = True):
        self.start(headless=headless, keep_open=True)
        with self._lock:
            if self.status not in {"running", "busy"} or self._commands is None:
                raise RuntimeError(self.error or "浏览器不可用")
            result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
            self._commands.put({"type": "run", "callback": callback, "result": result})
        state, payload = result.get()
        if state == "error":
            raise payload
        return payload

    def _touch_locked(self, message: str | None = None) -> None:
        now = time.time()
        self.last_used_at = now
        self.updated_at = now
        if message:
            self.message = message

    def _close_if_idle_locked(self) -> None:
        if self.status not in {"running", "busy"} or self.active_operations:
            return
        if (
            self.keep_open
            and self.idle_timeout_seconds > 0
            and self.last_used_at
            and time.time() - self.last_used_at >= self.idle_timeout_seconds
        ):
            commands = self._commands
            if commands is not None:
                result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
                commands.put({"type": "close", "reason": "idle_timeout", "result": result})
                with contextlib.suppress(queue.Empty):
                    result.get(timeout=5)
            self._mark_closed_locked("idle_timeout")

    def _worker_main(self, headless: bool, start_result: "queue.Queue[tuple[str, Any]]", commands: "queue.Queue[dict[str, Any]]") -> None:
        playwright_manager = None
        context = None
        try:
            config_dir = zlibrary_config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            config_dir.chmod(0o700)
            playwright_manager = sync_playwright_factory()
            playwright = playwright_manager.__enter__()
            launch_choice = choose_chromium_launch_options(playwright.chromium)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(config_dir / "browser_profile"),
                headless=headless,
                accept_downloads=True,
                downloads_path=str(WORKSPACE_ROOT),
                args=["--disable-blink-features=AutomationControlled"],
                **launch_choice.options,
            )
            now = time.time()
            with self._lock:
                self.started_at = now
                self.last_used_at = now
                self.status = "running"
                self.message = launch_choice.log or "浏览器已启动"
                self.updated_at = now
            start_result.put(("ok", None))

            while True:
                command = commands.get()
                if command["type"] == "close":
                    self._worker_close_context(context, playwright_manager)
                    context = None
                    playwright_manager = None
                    command["result"].put(("ok", None))
                    return
                if command["type"] != "run":
                    continue
                result_queue = command["result"]
                callback = command["callback"]
                page = None
                try:
                    with self._lock:
                        self.active_operations += 1
                        self.status = "busy"
                        self.message = "浏览器正在执行任务"
                        self._touch_locked()
                    page = context.new_page()
                    page.set_default_timeout(60000)
                    result_queue.put(("ok", callback(page)))
                except Exception as exc:
                    result_queue.put(("error", exc))
                finally:
                    if page is not None:
                        with contextlib.suppress(Exception):
                            page.close()
                    with self._lock:
                        self.active_operations = max(self.active_operations - 1, 0)
                        if self.status == "busy":
                            self.status = "running"
                        self.message = "浏览器空闲"
                        self._touch_locked()
        except Exception as exc:
            message = format_zlibrary_login_error(exc)
            with self._lock:
                self.status = "crashed"
                self.error = message
                self.message = f"浏览器启动失败: {message}"
                self.updated_at = time.time()
            start_result.put(("error", message))
        finally:
            if context is not None or playwright_manager is not None:
                self._worker_close_context(context, playwright_manager)

    @staticmethod
    def _worker_close_context(context: Any, playwright_manager: Any) -> None:
        if context is not None:
            with contextlib.suppress(Exception):
                context.close()
        if playwright_manager is not None:
            with contextlib.suppress(Exception):
                playwright_manager.__exit__(None, None, None)


MANAGED_BROWSER = ManagedBrowserSession()


def get_browser_status() -> dict[str, Any]:
    return MANAGED_BROWSER.serialize()


def start_managed_browser(
    headless: bool = True,
    keep_open: bool = True,
    idle_timeout_seconds: int | None = None,
) -> dict[str, Any]:
    return MANAGED_BROWSER.start(headless=headless, keep_open=keep_open, idle_timeout_seconds=idle_timeout_seconds)


def close_managed_browser(force: bool = False) -> dict[str, Any]:
    return MANAGED_BROWSER.close(force=force)


def restart_managed_browser(headless: bool = True, keep_open: bool = True) -> dict[str, Any]:
    return MANAGED_BROWSER.restart(headless=headless, keep_open=keep_open)


@dataclass
class UploadTask:
    id: str
    zlibrary_url: str
    notebook_id: str | None = None
    notebook_title: str | None = None
    mode: str = "remote"
    local_path: str | None = None
    selected_source_path: str | None = None
    selected_source_paths: list[str] = field(default_factory=list)
    processing_strategy: str | None = None
    downloaded_file: str | None = None
    final_file: str | None = None
    file_format: str | None = None
    stage: str = "queued"
    status: str = "queued"
    progress: dict[str, Any] = field(default_factory=lambda: {
        "phase": "queued",
        "percent": 0,
        "label": "排队中",
        "detail": "",
    })
    logs: list[str] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)
    uploads: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    workspace_root: Path = WORKSPACE_ROOT


class ZLibraryLoginSession:
    def __init__(self, timeout_seconds: int = ZLIBRARY_LOGIN_TIMEOUT_SECONDS):
        self.id = uuid.uuid4().hex
        self.status = "starting"
        self.logs = ["正在打开 Z-Library 登录窗口"]
        self.error: str | None = None
        self.started_at = time.time()
        self.updated_at = self.started_at
        self.timeout_seconds = timeout_seconds
        self._save_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def is_active(self) -> bool:
        with self._lock:
            return self.status in {"starting", "waiting", "saving"}

    def request_save(self) -> None:
        with self._lock:
            if self.status not in {"starting", "waiting"}:
                raise BadRequest("当前没有可保存的 Z-Library 登录窗口")
            self.status = "saving"
            self.logs.append("收到保存会话请求")
            self.updated_at = time.time()
        self._save_requested.set()

    def request_cancel(self) -> None:
        with self._lock:
            if self.status not in {"starting", "waiting", "saving"}:
                return
            self.status = "cancelled"
            self.logs.append("登录流程已取消")
            self.updated_at = time.time()
        self._cancel_requested.set()

    def serialize(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "logs": list(self.logs),
                "error": self.error,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
            }

    def _set_status(self, status: str, log: str | None = None, error: str | None = None) -> None:
        with self._lock:
            self.status = status
            if log:
                self.logs.append(log)
            if error:
                self.error = error
            self.updated_at = time.time()

    def _run(self) -> None:
        browser = None
        try:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError(
                    f"Playwright 未安装。请在当前后端 Python 环境运行: {sys.executable} -m pip install -r requirements.txt"
                ) from exc

            config_dir = zlibrary_config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            config_dir.chmod(0o700)

            with sync_playwright() as playwright:
                launch_choice = choose_chromium_launch_options(playwright.chromium)
                if launch_choice.log:
                    self._set_status("starting", launch_choice.log)
                browser = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(config_dir / "browser_profile"),
                    headless=False,
                    args=["--disable-blink-features=AutomationControlled"],
                    **launch_choice.options,
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
                page.goto("https://zh.zlib.li/", wait_until="domcontentloaded", timeout=30000)
                self._set_status("waiting", "浏览器已打开，请在弹出的窗口中完成 Z-Library 登录")

                deadline = time.time() + self.timeout_seconds
                while time.time() < deadline:
                    if self._cancel_requested.is_set():
                        self._set_status("cancelled", "浏览器窗口已关闭")
                        return
                    if self._save_requested.wait(timeout=0.5):
                        storage_state = zlibrary_storage_state_path()
                        browser.storage_state(path=str(storage_state))
                        storage_state.chmod(0o600)
                        self._set_status("completed", f"会话已保存: {storage_state}")
                        return

                self._set_status("failed", "登录窗口已超时，请重新发起登录", "登录窗口已超时，请重新发起登录")
        except Exception as exc:
            message = format_zlibrary_login_error(exc)
            self._set_status("failed", error=message, log=f"登录失败: {message}")
        finally:
            if browser is not None:
                with contextlib.suppress(Exception):
                    browser.close()


def format_zlibrary_login_error(error: Exception) -> str:
    message = str(error)
    if (
        "Executable doesn't exist" in message
        or "playwright install" in message
        or "没有找到 Playwright Chromium" in message
    ):
        return (
            "没有找到可用浏览器，无法弹出登录窗口。"
            f"请运行: {sys.executable} -m playwright install chromium"
        )
    if "No module named 'playwright'" in message:
        return (
            "Playwright 未安装，无法弹出登录窗口。"
            f"请运行: {sys.executable} -m pip install -r requirements.txt"
        )
    return message


def parse_notebooks(stdout: str) -> list[dict[str, str]]:
    data = json.loads(stdout or "[]")
    raw_items = data.get("notebooks", data) if isinstance(data, dict) else data
    notebooks = []

    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        notebook_id = item.get("id") or item.get("notebook_id")
        title = item.get("title") or item.get("name")
        if notebook_id and title:
            notebooks.append({"id": notebook_id, "title": title})

    return notebooks


def parse_created_notebook(stdout: str) -> dict[str, str]:
    data = json.loads(stdout or "{}")
    notebook = data.get("notebook", data)
    notebook_id = notebook.get("id") or notebook.get("notebook_id")
    title = notebook.get("title") or notebook.get("name")
    if not notebook_id:
        raise ValueError("notebooklm create did not return a notebook id")
    return {"id": notebook_id, "title": title or notebook_id}


def safe_task_id(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return text or uuid.uuid4().hex


def canonical_zlibrary_key(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(str(url).strip())
    path = parsed.path or str(url).strip()
    path = re.sub(r"/+", "/", path).strip("/")
    if not path:
        return str(url).strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")

    match = re.search(r"(?:^|/)(book/[^/?#]+(?:/[^/?#]+)?)", path)
    if match:
        return match.group(1).rstrip("/")
    return path.rstrip("/")


def task_manifest_path(task_id: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    return workspace_root / safe_task_id(task_id) / "manifest.json"


def serialize_task(task: UploadTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "zlibrary_url": task.zlibrary_url,
        "book_key": canonical_zlibrary_key(task.zlibrary_url),
        "notebook_id": task.notebook_id,
        "notebook_title": task.notebook_title,
        "mode": task.mode,
        "local_path": task.local_path,
        "selected_source_path": task.selected_source_path,
        "selected_source_paths": task.selected_source_paths,
        "processing_strategy": task.processing_strategy,
        "downloaded_file": task.downloaded_file,
        "final_file": task.final_file,
        "file_format": task.file_format,
        "stage": task.stage,
        "status": task.status,
        "progress": task.progress,
        "logs": task.logs,
        "parts": task.parts,
        "uploads": task.uploads,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def save_task_manifest(task: UploadTask) -> None:
    task.updated_at = time.time()
    path = task_manifest_path(task.id, task.workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialize_task(task), ensure_ascii=False, indent=2), encoding="utf-8")


def set_task_progress(task: UploadTask, phase: str, percent: int, label: str, detail: str = "") -> None:
    task.stage = phase
    task.progress = {
        "phase": phase,
        "percent": max(0, min(100, int(percent))),
        "label": label,
        "detail": detail,
    }


def fail_task(task: UploadTask, error: Exception | str, label: str = "任务失败") -> None:
    message = str(error)
    task.error = message
    task.status = "failed"
    set_task_progress(task, "failed", 100, label, message)
    task.logs.append(f"失败: {message}")


def task_operation_lock(task_id: str) -> threading.Lock:
    safe_id = safe_task_id(task_id)
    with TASKS_LOCK:
        lock = TASK_OPERATION_LOCKS.get(safe_id)
        if lock is None:
            lock = threading.Lock()
            TASK_OPERATION_LOCKS[safe_id] = lock
        return lock


def resolve_safe_local_file(path_value: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    raw_path = Path(path_value).expanduser()
    file_path = raw_path.resolve()
    root = workspace_root.resolve()
    try:
        file_path.relative_to(root)
    except ValueError as exc:
        raise BadRequest("只能选择任务工作区内的本地文件") from exc
    if not file_path.is_file():
        raise BadRequest("本地文件不存在")
    return file_path


def describe_local_file(path_value: str | Path | None, workspace_root: Path) -> dict[str, Any] | None:
    if not path_value:
        return None
    try:
        file_path = resolve_safe_local_file(str(path_value), workspace_root)
    except BadRequest:
        return None
    stat = file_path.stat()
    return {
        "path": str(file_path),
        "filename": file_path.name,
        "extension": file_path.suffix.lower().lstrip("."),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def describe_part(path_value: str | Path, index: int, workspace_root: Path, status: str = "ready") -> dict[str, Any]:
    file_info = describe_local_file(path_value, workspace_root) or {
        "path": str(path_value),
        "filename": Path(path_value).name,
        "extension": Path(path_value).suffix.lower().lstrip("."),
        "size": 0,
        "mtime": None,
    }
    return {
        "index": index,
        "path": file_info["path"],
        "filename": file_info["filename"],
        "extension": file_info["extension"],
        "size": file_info["size"],
        "status": status,
        "source_id": None,
        "error": None,
    }


def normalize_resolved_path(path_value: str | Path) -> str:
    try:
        return str(Path(path_value).resolve())
    except Exception:
        return str(path_value)


def part_matches_path(part: dict[str, Any], source_path: str) -> bool:
    part_path = part.get("path")
    return bool(part_path and normalize_resolved_path(str(part_path)) == source_path)


def source_records_for_path(uploads: list[dict[str, Any]], source_path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for upload in uploads:
        if not isinstance(upload, dict):
            continue
        for record in upload.get("source_records") or []:
            if not isinstance(record, dict):
                continue
            if normalize_resolved_path(str(record.get("source_path") or "")) == source_path:
                records.append(record)
        if normalize_resolved_path(str(upload.get("source_path") or "")) == source_path:
            records.append({
                "status": upload.get("status"),
                "notebook_id": upload.get("notebook_id"),
                "notebook_title": upload.get("notebook_title"),
                "title": upload.get("title"),
                "source_path": source_path,
                "source_id": upload.get("source_id") or (upload.get("source_ids") or [None])[0],
                "error": upload.get("error"),
                "updated_at": upload.get("updated_at"),
            })
    return sorted(records, key=lambda item: float(item.get("updated_at") or 0), reverse=True)


def enrich_source_with_upload_records(source: dict[str, Any], uploads: list[dict[str, Any]]) -> dict[str, Any]:
    records = source_records_for_path(uploads, normalize_resolved_path(source["path"]))
    if not records:
        return source
    latest = records[0]
    return {
        **source,
        "upload_records": records,
        "last_notebook_id": latest.get("notebook_id"),
        "last_notebook_title": latest.get("notebook_title"),
        "last_uploaded_at": latest.get("updated_at"),
    }


def resolve_existing_upload_files(task: UploadTask) -> list[Path]:
    if task.parts:
        return [
            resolve_safe_local_file(str(part["path"]), task.workspace_root)
            for part in task.parts
            if isinstance(part, dict) and part.get("path")
        ]
    raw_path = task.final_file or task.downloaded_file or task.local_path
    if not raw_path:
        return []
    return [resolve_safe_local_file(str(raw_path), task.workspace_root)]


def resolve_selected_source_files(task: UploadTask) -> list[Path]:
    source_paths = task.selected_source_paths or ([task.selected_source_path] if task.selected_source_path else [])
    if not source_paths:
        raise ValueError("请选择要上传的来源")
    seen: set[str] = set()
    files: list[Path] = []
    for source_path in source_paths:
        source_file = resolve_safe_local_file(str(source_path), task.workspace_root)
        normalized = str(source_file.resolve())
        if normalized in seen:
            continue
        seen.add(normalized)
        files.append(source_file)
    return files


def create_versioned_processing_input(local_file: Path, task: UploadTask) -> Path:
    version_dir = task_manifest_path(task.id, task.workspace_root).parent / "processing_versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    index = 2
    while True:
        candidate = version_dir / f"{local_file.stem}_v{index:03d}{local_file.suffix}"
        if not candidate.exists():
            shutil.copy2(local_file, candidate)
            return candidate
        index += 1


def record_processed_files(task: UploadTask, final_file: Path | list[Path]) -> None:
    files = final_file if isinstance(final_file, list) else [final_file]
    task.final_file = str(files[0]) if files else None
    if isinstance(final_file, list):
        task.parts = [
            describe_part(file_path, index, task.workspace_root)
            for index, file_path in enumerate(final_file, 1)
        ]
    else:
        task.parts = []


def record_upload_result(task: UploadTask, result: dict[str, Any]) -> None:
    upload_files = resolve_existing_upload_files(task)
    if upload_files:
        record_sources_upload_result(task, upload_files, result)
        return

    task.result = result
    source_ids = list(result.get("source_ids") or [])
    failed_by_path = {}
    for item in result.get("failed_chunks") or []:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        raw_path = str(item.get("file"))
        error = str(item.get("error") or "上传失败")
        failed_by_path[raw_path] = error
        with contextlib.suppress(Exception):
            failed_by_path[str(Path(raw_path).resolve())] = error

    if task.parts:
        for index, part in enumerate(task.parts):
            part_path = str(part.get("path") or "")
            if part_path in failed_by_path:
                part["status"] = "failed"
                part["error"] = failed_by_path[part_path]
                continue
            if index < len(source_ids):
                part["status"] = "uploaded"
                part["source_id"] = source_ids[index]
                part["error"] = None
            elif not result.get("success"):
                part["status"] = "pending"

    single_source_id = result.get("source_id")
    upload_record = {
        "status": "completed" if result.get("success") else "failed",
        "notebook_id": result.get("notebook_id") or task.notebook_id,
        "notebook_title": task.notebook_title,
        "title": result.get("title"),
        "source_id": single_source_id,
        "source_ids": source_ids or ([single_source_id] if single_source_id else []),
        "chunks": result.get("chunks") or (len(task.parts) if task.parts else None),
        "error": result.get("error"),
        "updated_at": time.time(),
    }
    task.uploads.append(upload_record)


def record_sources_upload_result(task: UploadTask, source_files: list[Path], result: dict[str, Any]) -> None:
    task.result = result
    updated_at = time.time()
    source_ids = list(result.get("source_ids") or [])
    failed_by_path: dict[str, str] = {}
    for item in result.get("failed_chunks") or []:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        failed_by_path[normalize_resolved_path(str(item.get("file")))] = str(item.get("error") or "上传失败")

    source_records: list[dict[str, Any]] = []
    success_index = 0
    for source_file in source_files:
        source_path = str(source_file.resolve())
        source_error = failed_by_path.get(source_path)
        source_id = None if source_error else (source_ids[success_index] if success_index < len(source_ids) else None)
        if source_error is None and source_id:
            success_index += 1
        source_success = bool(source_id) or (result.get("success") and not source_error and len(source_files) == 1)
        if source_success and not source_id:
            source_id = result.get("source_id") or (result.get("source_ids") or [None])[0]

        for part in task.parts:
            if not isinstance(part, dict) or not part_matches_path(part, source_path):
                continue
            if source_success:
                part["status"] = "uploaded"
                part["source_id"] = source_id
                part["error"] = None
            else:
                part["status"] = "failed"
                part["error"] = source_error or result.get("error") or "上传失败"

        source_records.append({
            "status": "completed" if source_success else "failed",
            "notebook_id": result.get("notebook_id") or task.notebook_id,
            "notebook_title": task.notebook_title,
            "title": result.get("title"),
            "source_path": source_path,
            "source_filename": source_file.name,
            "source_id": source_id,
            "error": None if source_success else source_error or result.get("error") or "上传失败",
            "updated_at": updated_at,
        })

    single_source_id = result.get("source_id")
    upload_record = {
        "scope": "source_batch" if len(source_files) != 1 else "single_source",
        "status": "completed" if result.get("success") else "failed",
        "notebook_id": result.get("notebook_id") or task.notebook_id,
        "notebook_title": task.notebook_title,
        "title": result.get("title"),
        "source_id": single_source_id,
        "source_ids": source_ids or ([single_source_id] if single_source_id else []),
        "chunks": result.get("chunks") or len(source_files),
        "source_records": source_records,
        "error": result.get("error"),
        "updated_at": updated_at,
    }
    task.uploads.append(upload_record)


def record_single_source_upload_result(task: UploadTask, source_file: Path, result: dict[str, Any]) -> None:
    matched_part = any(isinstance(part, dict) and part_matches_path(part, str(source_file.resolve())) for part in task.parts)
    record_sources_upload_result(task, [source_file], result)
    if not matched_part and result.get("success"):
        task.stage = "uploaded"


def build_upload_sources(manifest: dict[str, Any], workspace_root: Path) -> list[dict[str, Any]]:
    raw_parts = manifest.get("parts") or []
    sources: list[dict[str, Any]] = []
    uploads = [item for item in manifest.get("uploads") or [] if isinstance(item, dict)]

    if raw_parts:
        total = len(raw_parts)
        for index, raw_part in enumerate(raw_parts, 1):
            if not isinstance(raw_part, dict):
                continue
            part_info = describe_local_file(raw_part.get("path"), workspace_root)
            if not part_info:
                continue
            source = {
                **part_info,
                "kind": "part",
                "index": raw_part.get("index") or index,
                "total": total,
                "status": raw_part.get("status", "ready"),
                "source_id": raw_part.get("source_id"),
                "error": raw_part.get("error"),
            }
            sources.append(enrich_source_with_upload_records(source, uploads))
        return sources

    raw_path = manifest.get("final_file") or manifest.get("downloaded_file") or manifest.get("local_path")
    file_info = describe_local_file(raw_path, workspace_root)
    if not file_info:
        return []

    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    successful_upload = next((item for item in reversed(uploads) if item.get("status") == "completed"), None)
    failed_upload = next((item for item in reversed(uploads) if item.get("status") == "failed"), None)
    stage = str(manifest.get("stage") or "")
    status = str(manifest.get("status") or "")

    source_status = "ready"
    source_id = None
    error = None
    if successful_upload:
        source_status = "uploaded"
        source_id = successful_upload.get("source_id") or (successful_upload.get("source_ids") or [None])[0]
    elif result.get("success"):
        source_status = "uploaded"
        source_id = result.get("source_id") or (result.get("source_ids") or [None])[0]
    elif stage == "uploading" or status == "running":
        source_status = "uploading"
    elif failed_upload or status == "failed":
        source_status = "failed"
        error = (failed_upload or {}).get("error") or result.get("error") or manifest.get("error")

    source = {
        **file_info,
        "kind": "file",
        "index": 1,
        "total": 1,
        "status": source_status,
        "source_id": source_id,
        "error": error,
    }
    return [enrich_source_with_upload_records(source, uploads)]


def summarize_upload_sources(upload_sources: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(upload_sources)
    uploaded = sum(1 for source in upload_sources if source.get("status") == "uploaded")
    failed = sum(1 for source in upload_sources if source.get("status") == "failed")
    uploading = sum(1 for source in upload_sources if source.get("status") == "uploading")
    ready = max(total - uploaded - failed - uploading, 0)

    if total == 0:
        state = "empty"
    elif uploaded == total:
        state = "uploaded"
    elif uploading:
        state = "uploading"
    elif failed:
        state = "failed"
    else:
        state = "ready"

    return {
        "total": total,
        "uploaded": uploaded,
        "failed": failed,
        "uploading": uploading,
        "ready": ready,
        "state": state,
    }


def _asset_from_manifest(manifest: dict[str, Any], workspace_root: Path) -> dict[str, Any] | None:
    raw_path = manifest.get("final_file") or manifest.get("downloaded_file") or manifest.get("local_path")
    if not raw_path:
        return None
    try:
        local_path = resolve_safe_local_file(str(raw_path), workspace_root)
    except BadRequest:
        return None

    stat = local_path.stat()
    original_file = describe_local_file(manifest.get("downloaded_file") or manifest.get("local_path"), workspace_root)
    processed_file = describe_local_file(manifest.get("final_file"), workspace_root)
    parts = []
    for raw_part in manifest.get("parts") or []:
        if not isinstance(raw_part, dict):
            continue
        part_info = describe_local_file(raw_part.get("path"), workspace_root)
        if not part_info:
            continue
        parts.append({
            **part_info,
            "index": raw_part.get("index"),
            "status": raw_part.get("status", "ready"),
            "source_id": raw_part.get("source_id"),
            "error": raw_part.get("error"),
        })

    upload_sources = build_upload_sources(manifest, workspace_root)
    upload_summary = summarize_upload_sources(upload_sources)

    return {
        "task_id": manifest.get("id") or local_path.parent.parent.name,
        "filename": local_path.name,
        "local_path": str(local_path),
        "extension": local_path.suffix.lower().lstrip(".") or str(manifest.get("file_format") or ""),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mode": manifest.get("mode", "remote"),
        "status": manifest.get("status", "downloaded"),
        "stage": manifest.get("stage"),
        "zlibrary_url": manifest.get("zlibrary_url"),
        "book_key": manifest.get("book_key") or canonical_zlibrary_key(manifest.get("zlibrary_url")),
        "notebook_id": manifest.get("notebook_id"),
        "notebook_title": manifest.get("notebook_title"),
        "file_format": manifest.get("file_format"),
        "error": manifest.get("error"),
        "progress": manifest.get("progress") or {
            "phase": manifest.get("stage") or manifest.get("status") or "ready",
            "percent": 100 if manifest.get("status") == "completed" else 0,
            "label": str(manifest.get("stage") or manifest.get("status") or "ready"),
            "detail": "",
        },
        "result": manifest.get("result"),
        "original_file": original_file,
        "processed_file": processed_file,
        "parts": parts,
        "upload_sources": upload_sources,
        "upload_summary": upload_summary,
        "uploads": manifest.get("uploads") or [],
        "downloaded_file": manifest.get("downloaded_file"),
        "final_file": manifest.get("final_file"),
        "updated_at": manifest.get("updated_at", stat.st_mtime),
    }


def scan_local_assets(workspace_root: Path = WORKSPACE_ROOT) -> list[dict[str, Any]]:
    if not workspace_root.exists():
        return []

    assets = []
    for manifest_path in workspace_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        asset = _asset_from_manifest(manifest, workspace_root)
        if asset:
            assets.append(asset)

    return sorted(assets, key=lambda item: float(item.get("updated_at") or 0), reverse=True)


def task_from_manifest(manifest: dict[str, Any], workspace_root: Path = WORKSPACE_ROOT) -> UploadTask:
    task = UploadTask(
        id=safe_task_id(str(manifest.get("id") or uuid.uuid4().hex)),
        zlibrary_url=str(manifest.get("zlibrary_url") or ""),
        notebook_id=manifest.get("notebook_id"),
        notebook_title=manifest.get("notebook_title"),
        mode=str(manifest.get("mode") or "remote"),
        local_path=manifest.get("local_path"),
        selected_source_path=manifest.get("selected_source_path"),
        selected_source_paths=list(manifest.get("selected_source_paths") or []),
        processing_strategy=manifest.get("processing_strategy"),
        downloaded_file=manifest.get("downloaded_file"),
        final_file=manifest.get("final_file"),
        file_format=manifest.get("file_format"),
        stage=str(manifest.get("stage") or "queued"),
        status=str(manifest.get("status") or "queued"),
        progress=dict(manifest.get("progress") or {
            "phase": manifest.get("stage") or manifest.get("status") or "queued",
            "percent": 100 if manifest.get("status") in {"completed", "failed"} else 0,
            "label": str(manifest.get("stage") or manifest.get("status") or "queued"),
            "detail": str(manifest.get("error") or ""),
        }),
        logs=list(manifest.get("logs") or []),
        parts=list(manifest.get("parts") or []),
        uploads=list(manifest.get("uploads") or []),
        result=manifest.get("result") if isinstance(manifest.get("result"), dict) else None,
        error=manifest.get("error"),
        created_at=float(manifest.get("created_at") or time.time()),
        updated_at=float(manifest.get("updated_at") or time.time()),
        workspace_root=workspace_root,
    )
    return task


def load_task_from_manifest(task_id: str, workspace_root: Path = WORKSPACE_ROOT) -> UploadTask | None:
    path = task_manifest_path(task_id, workspace_root)
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    task = task_from_manifest(manifest, workspace_root)
    with TASKS_LOCK:
        TASKS[task.id] = task
    return task


def scan_task_manifests(workspace_root: Path = WORKSPACE_ROOT) -> list[UploadTask]:
    if not workspace_root.exists():
        return []
    tasks: list[UploadTask] = []
    for manifest_path in workspace_root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task = task_from_manifest(manifest, workspace_root)
        tasks.append(task)
    return sorted(tasks, key=lambda item: item.updated_at, reverse=True)


def create_task(zlibrary_url: str, notebook_id: str | None = None, notebook_title: str | None = None) -> UploadTask:
    task = UploadTask(
        id=uuid.uuid4().hex,
        zlibrary_url=zlibrary_url,
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        logs=["任务已创建"],
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def create_download_task(zlibrary_url: str, workspace_root: Path = WORKSPACE_ROOT) -> UploadTask:
    task = UploadTask(
        id=uuid.uuid4().hex,
        zlibrary_url=zlibrary_url,
        mode="download",
        logs=["下载到本地任务已创建"],
        workspace_root=workspace_root,
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def create_local_upload_task(
    local_path: str,
    notebook_id: str | None = None,
    notebook_title: str | None = None,
    workspace_root: Path = WORKSPACE_ROOT,
    task_id: str | None = None,
) -> UploadTask:
    file_path = resolve_safe_local_file(local_path, workspace_root)
    manifest: dict[str, Any] = {}
    if task_id:
        manifest_path = task_manifest_path(task_id, workspace_root)
        if manifest_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task = UploadTask(
        id=safe_task_id(task_id) if task_id else uuid.uuid4().hex,
        zlibrary_url=str(manifest.get("zlibrary_url") or ""),
        notebook_id=notebook_id or manifest.get("notebook_id"),
        notebook_title=notebook_title or manifest.get("notebook_title"),
        mode=str(manifest.get("mode") or "local"),
        local_path=str(manifest.get("local_path") or file_path),
        downloaded_file=str(manifest.get("downloaded_file") or file_path),
        final_file=str(manifest.get("final_file") or file_path),
        file_format=file_path.suffix.lower().lstrip(".") or manifest.get("file_format") or None,
        stage="queued",
        logs=list(manifest.get("logs") or []) + ["本地文件上传任务已创建"],
        parts=list(manifest.get("parts") or []),
        uploads=list(manifest.get("uploads") or []),
        workspace_root=workspace_root,
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def create_process_local_task(
    local_path: str,
    workspace_root: Path = WORKSPACE_ROOT,
    task_id: str | None = None,
    strategy: str | None = None,
) -> UploadTask:
    file_path = resolve_safe_local_file(local_path, workspace_root)
    manifest: dict[str, Any] = {}
    if task_id:
        manifest_path = task_manifest_path(task_id, workspace_root)
        if manifest_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    existing_parts = list(manifest.get("parts") or [])
    normalized_strategy = strategy.strip().lower() if isinstance(strategy, str) and strategy.strip() else None
    if normalized_strategy and normalized_strategy not in {"keep", "replace", "version"}:
        raise BadRequest("处理策略必须是 keep、replace 或 version")
    if existing_parts and normalized_strategy is None:
        raise BadRequest("这个文件已经处理/分片过，请选择保留、覆盖或生成新版本")
    task = UploadTask(
        id=safe_task_id(task_id) if task_id else uuid.uuid4().hex,
        zlibrary_url=str(manifest.get("zlibrary_url") or ""),
        notebook_id=manifest.get("notebook_id"),
        notebook_title=manifest.get("notebook_title"),
        mode=str(manifest.get("mode") or "process"),
        local_path=str(manifest.get("local_path") or file_path),
        downloaded_file=str(manifest.get("downloaded_file") or file_path),
        final_file=str(manifest.get("final_file") or file_path),
        file_format=file_path.suffix.lower().lstrip(".") or manifest.get("file_format") or None,
        stage="queued",
        logs=list(manifest.get("logs") or []) + ["本地文件处理任务已创建"],
        parts=list(manifest.get("parts") or []),
        uploads=list(manifest.get("uploads") or []),
        result=manifest.get("result"),
        error=manifest.get("error"),
        processing_strategy=normalized_strategy,
        workspace_root=workspace_root,
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def create_sources_upload_task(
    source_paths: list[str],
    notebook_id: str | None = None,
    notebook_title: str | None = None,
    workspace_root: Path = WORKSPACE_ROOT,
    task_id: str | None = None,
) -> UploadTask:
    if not source_paths:
        raise BadRequest("请选择要上传的来源")
    resolved_sources = [resolve_safe_local_file(source_path, workspace_root) for source_path in source_paths]
    manifest: dict[str, Any] = {}
    if task_id:
        manifest_path = task_manifest_path(task_id, workspace_root)
        if manifest_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    task = UploadTask(
        id=safe_task_id(task_id) if task_id else uuid.uuid4().hex,
        zlibrary_url=str(manifest.get("zlibrary_url") or ""),
        notebook_id=notebook_id or manifest.get("notebook_id"),
        notebook_title=notebook_title or manifest.get("notebook_title"),
        mode=str(manifest.get("mode") or "sources"),
        local_path=str(manifest.get("local_path") or manifest.get("downloaded_file") or resolved_sources[0]),
        selected_source_path=str(resolved_sources[0]),
        selected_source_paths=[str(source.resolve()) for source in resolved_sources],
        downloaded_file=manifest.get("downloaded_file") or str(resolved_sources[0]),
        final_file=manifest.get("final_file") or str(resolved_sources[0]),
        file_format=manifest.get("file_format") or resolved_sources[0].suffix.lower().lstrip(".") or None,
        stage="queued",
        logs=list(manifest.get("logs") or []) + [f"批量来源上传任务已创建: {len(resolved_sources)} 个来源"],
        parts=list(manifest.get("parts") or []),
        uploads=list(manifest.get("uploads") or []),
        result=manifest.get("result"),
        error=manifest.get("error"),
        workspace_root=workspace_root,
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def create_source_upload_task(
    source_path: str,
    notebook_id: str | None = None,
    notebook_title: str | None = None,
    workspace_root: Path = WORKSPACE_ROOT,
    task_id: str | None = None,
) -> UploadTask:
    source_file = resolve_safe_local_file(source_path, workspace_root)
    manifest: dict[str, Any] = {}
    if task_id:
        manifest_path = task_manifest_path(task_id, workspace_root)
        if manifest_path.exists():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    task = UploadTask(
        id=safe_task_id(task_id) if task_id else uuid.uuid4().hex,
        zlibrary_url=str(manifest.get("zlibrary_url") or ""),
        notebook_id=notebook_id or manifest.get("notebook_id"),
        notebook_title=notebook_title or manifest.get("notebook_title"),
        mode=str(manifest.get("mode") or "source"),
        local_path=str(manifest.get("local_path") or manifest.get("downloaded_file") or source_file),
        selected_source_path=str(source_file),
        downloaded_file=manifest.get("downloaded_file") or str(source_file),
        final_file=manifest.get("final_file") or str(source_file),
        file_format=manifest.get("file_format") or source_file.suffix.lower().lstrip(".") or None,
        stage="queued",
        logs=list(manifest.get("logs") or []) + [f"单个来源上传任务已创建: {source_file.name}"],
        parts=list(manifest.get("parts") or []),
        uploads=list(manifest.get("uploads") or []),
        result=manifest.get("result"),
        error=manifest.get("error"),
        workspace_root=workspace_root,
    )
    with TASKS_LOCK:
        TASKS[task.id] = task
    save_task_manifest(task)
    return task


def zlibrary_config_dir() -> Path:
    return Path.home() / ".zlibrary"


def zlibrary_storage_state_path() -> Path:
    return zlibrary_config_dir() / "storage_state.json"


def get_current_zlibrary_login_session() -> ZLibraryLoginSession | None:
    with ZLIBRARY_LOGIN_LOCK:
        return ZLIBRARY_LOGIN_SESSION


def get_zlibrary_auth_status() -> dict[str, Any]:
    storage_state = zlibrary_storage_state_path()
    session = get_current_zlibrary_login_session()
    saved = storage_state.exists() and storage_state.stat().st_size > 0
    status = "saved" if saved else "missing"
    message = "已保存 Z-Library 会话" if saved else "未保存 Z-Library 会话"

    if session and session.is_active():
        status = session.serialize()["status"]
        message = "Z-Library 登录窗口已打开，请在浏览器完成登录"
    elif session and session.serialize()["status"] == "failed":
        status = "failed"
        message = session.serialize().get("error") or "Z-Library 登录失败"

    return {
        "logged_in": saved,
        "status": status,
        "message": message,
        "storage_state": str(storage_state),
        "session": session.serialize() if session else None,
    }


def start_zlibrary_login() -> dict[str, Any]:
    global ZLIBRARY_LOGIN_SESSION
    with ZLIBRARY_LOGIN_LOCK:
        if ZLIBRARY_LOGIN_SESSION and ZLIBRARY_LOGIN_SESSION.is_active():
            return get_zlibrary_auth_status()
        ZLIBRARY_LOGIN_SESSION = ZLibraryLoginSession()
        ZLIBRARY_LOGIN_SESSION.start()
    return get_zlibrary_auth_status()


def complete_zlibrary_login() -> dict[str, Any]:
    session = get_current_zlibrary_login_session()
    if not session:
        raise BadRequest("没有正在进行的 Z-Library 登录流程")
    session.request_save()
    return get_zlibrary_auth_status()


def cancel_zlibrary_login() -> dict[str, Any]:
    session = get_current_zlibrary_login_session()
    if session:
        session.request_cancel()
    return get_zlibrary_auth_status()


def resolve_notebooklm_command() -> str | None:
    command = shutil.which("notebooklm")
    if command:
        return command

    sibling_command = Path(sys.executable).with_name("notebooklm")
    if sibling_command.is_file():
        return str(sibling_command)

    return None


def notebooklm_command_available() -> bool:
    return resolve_notebooklm_command() is not None


def cache_notebooklm_auth_status(status: dict[str, Any]) -> dict[str, Any]:
    global NOTEBOOKLM_STATUS_CACHE
    with NOTEBOOKLM_STATUS_CACHE_LOCK:
        NOTEBOOKLM_STATUS_CACHE = dict(status)
    return status


def get_cached_notebooklm_auth_status() -> dict[str, Any]:
    login_process = get_notebooklm_login_process_state()
    with NOTEBOOKLM_STATUS_CACHE_LOCK:
        cached = dict(NOTEBOOKLM_STATUS_CACHE) if NOTEBOOKLM_STATUS_CACHE else None

    if cached:
        cached["login_process"] = login_process
        return cached

    if not notebooklm_command_available():
        return {
            "installed": False,
            "logged_in": False,
            "status": "missing",
            "message": "未找到 notebooklm 命令，请先安装 NotebookLM CLI",
            "login_process": login_process,
        }

    return {
        "installed": True,
        "logged_in": False,
        "status": "unchecked",
        "message": "NotebookLM 状态尚未刷新",
        "login_process": login_process,
    }


def get_notebooklm_login_process_state() -> dict[str, Any] | None:
    with NOTEBOOKLM_LOGIN_LOCK:
        process = NOTEBOOKLM_LOGIN_PROCESS
    if not process:
        return None

    returncode = process.poll()
    if returncode is None:
        return {"status": "running", "returncode": None}
    return {"status": "exited", "returncode": returncode}


def run_notebooklm(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    command = resolve_notebooklm_command()
    if not command:
        raise RuntimeError("未找到 notebooklm 命令，请先安装并运行 notebooklm login")

    try:
        return subprocess.run(
            [command, *args],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 notebooklm 命令，请先安装并运行 notebooklm login") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("notebooklm 命令执行超时，请确认 CLI 没有卡在登录或网络请求中") from exc


def get_notebooklm_auth_status() -> dict[str, Any]:
    login_process = get_notebooklm_login_process_state()
    if not notebooklm_command_available():
        return cache_notebooklm_auth_status({
            "installed": False,
            "logged_in": False,
            "status": "missing",
            "message": "未找到 notebooklm 命令，请先安装 NotebookLM CLI",
            "login_process": login_process,
        })

    if login_process and login_process["status"] == "running":
        return cache_notebooklm_auth_status({
            "installed": True,
            "logged_in": False,
            "status": "login_running",
            "message": "NotebookLM 登录流程已启动，请在弹出的浏览器或终端提示中完成登录",
            "login_process": login_process,
        })

    try:
        result = run_notebooklm(["list", "--json"], timeout=8)
    except RuntimeError as exc:
        return cache_notebooklm_auth_status({
            "installed": True,
            "logged_in": False,
            "status": "error",
            "message": str(exc),
            "login_process": login_process,
        })

    if result.returncode == 0:
        try:
            notebooks = parse_notebooks(result.stdout)
        except Exception:
            notebooks = []
        return cache_notebooklm_auth_status({
            "installed": True,
            "logged_in": True,
            "status": "ready",
            "message": "NotebookLM CLI 已登录",
            "notebooks_count": len(notebooks),
            "login_process": login_process,
        })

    message = result.stderr.strip() or result.stdout.strip() or "NotebookLM CLI 尚未登录"
    return cache_notebooklm_auth_status({
        "installed": True,
        "logged_in": False,
        "status": "not_logged_in",
        "message": message,
        "login_process": login_process,
    })


def start_notebooklm_login() -> dict[str, Any]:
    global NOTEBOOKLM_LOGIN_PROCESS
    command = resolve_notebooklm_command()
    if not command:
        raise RuntimeError("未找到 notebooklm 命令，请先安装 NotebookLM CLI")

    with NOTEBOOKLM_LOGIN_LOCK:
        if NOTEBOOKLM_LOGIN_PROCESS and NOTEBOOKLM_LOGIN_PROCESS.poll() is None:
            return get_notebooklm_auth_status()
        try:
            login_command = [command, "login"]
            browser_channel = choose_system_browser_channel()
            if browser_channel:
                channel, _label = browser_channel
                login_command.extend(["--browser", channel])
            NOTEBOOKLM_LOGIN_PROCESS = subprocess.Popen(
                login_command,
                cwd=ROOT_DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 notebooklm 命令，请先安装 NotebookLM CLI") from exc
    return get_notebooklm_auth_status()


def cancel_notebooklm_login() -> dict[str, Any]:
    global NOTEBOOKLM_LOGIN_PROCESS
    with NOTEBOOKLM_LOGIN_LOCK:
        process = NOTEBOOKLM_LOGIN_PROCESS
        NOTEBOOKLM_LOGIN_PROCESS = None

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    installed = notebooklm_command_available()
    return cache_notebooklm_auth_status({
        "installed": installed,
        "logged_in": False,
        "status": "not_logged_in" if installed else "missing",
        "message": "NotebookLM 登录流程已取消" if installed else "未找到 notebooklm 命令，请先安装 NotebookLM CLI",
        "login_process": None,
    })


def get_auth_status(probe_notebooklm: bool = True) -> dict[str, Any]:
    notebooklm_status = (
        get_notebooklm_auth_status()
        if probe_notebooklm
        else get_cached_notebooklm_auth_status()
    )
    return {
        "zlibrary": get_zlibrary_auth_status(),
        "notebooklm": notebooklm_status,
    }


def list_notebooks() -> list[dict[str, str]]:
    result = run_notebooklm(["list", "--json"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "notebooklm list failed")
    return parse_notebooks(result.stdout)


def create_notebook(title: str) -> dict[str, str]:
    result = run_notebooklm(["create", title, "--json"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "notebooklm create failed")
    return parse_created_notebook(result.stdout)


def parse_search_limit(params: dict[str, list[str]]) -> int:
    raw_limit = params.get("limit", [str(DEFAULT_SEARCH_LIMIT)])[0]
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise BadRequest("搜索数量必须是正整数") from exc

    if limit < 1:
        raise BadRequest("搜索数量必须大于 0")
    return min(limit, MAX_SEARCH_LIMIT)


def search_zlibrary_managed(query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
    storage_state = zlibrary_storage_state_path()
    if not storage_state.exists():
        return []

    search_url = build_search_url(query)
    def run_search(page):
        page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as exc:
            if not is_networkidle_timeout(exc):
                raise
        html = page.content()
        return [result.__dict__ for result in extract_search_results(html, limit=limit)]

    return MANAGED_BROWSER.run_with_page(run_search, headless=True)


class Tee(io.StringIO):
    def __init__(self, task: UploadTask):
        super().__init__()
        self.task = task

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.task.logs.append(line)
        return len(text)


def download_with_preferred_browser(uploader: ZLibraryAutoUploader, url: str) -> tuple[Path | None, str | None]:
    if hasattr(uploader, "download_from_zlibrary_with_page"):
        return MANAGED_BROWSER.run_with_page(lambda page: uploader.download_from_zlibrary_with_page(page, url), headless=True)
    return asyncio.run(uploader.download_from_zlibrary(url))


def run_upload_task(task: UploadTask) -> None:
    task.status = "running"
    set_task_progress(task, "downloading", 10, "准备下载", "正在准备 Z-Library 下载")
    task.error = None
    task.logs.append("开始下载书籍")
    save_task_manifest(task)
    uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

    try:
        if not task.notebook_id:
            if not task.notebook_title:
                raise ValueError("请选择知识库或输入新知识库名称")
            set_task_progress(task, "creating_notebook", 8, "创建知识库", task.notebook_title)
            task.logs.append(f"创建知识库: {task.notebook_title}")
            save_task_manifest(task)
            notebook = create_notebook(task.notebook_title)
            task.notebook_id = notebook["id"]
            task.notebook_title = notebook["title"]
            save_task_manifest(task)

        with contextlib.redirect_stdout(Tee(task)):
            set_task_progress(task, "downloading", 25, "正在下载", "正在打开书籍页面并等待下载")
            save_task_manifest(task)
            downloaded = download_with_preferred_browser(uploader, task.zlibrary_url)
            if not downloaded:
                raise RuntimeError("下载失败，未返回文件")

            downloaded_file, file_format = downloaded
            if not downloaded_file:
                raise RuntimeError("下载失败，未找到文件")
            task.downloaded_file = str(downloaded_file)
            task.file_format = file_format
            set_task_progress(task, "downloaded", 58, "下载完成", Path(downloaded_file).name)
            save_task_manifest(task)

            set_task_progress(task, "converting", 68, "正在处理", "正在转换或分片为可上传来源")
            save_task_manifest(task)
            final_file = uploader.convert_to_txt(downloaded_file, file_format)
            record_processed_files(task, final_file)
            set_task_progress(task, "uploading", 82, "正在上传", "正在上传到 NotebookLM")
            save_task_manifest(task)
            result = uploader.upload_to_notebooklm(final_file, notebook_id=task.notebook_id)

        record_upload_result(task, result)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "上传失败"))

        set_task_progress(task, "uploaded", 100, "上传完成", task.notebook_title or task.notebook_id or "")
        task.status = "completed"
        task.logs.append("上传完成")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "上传失败" if task.downloaded_file else "下载失败")
        save_task_manifest(task)


def run_download_task(task: UploadTask) -> None:
    task.status = "running"
    set_task_progress(task, "downloading", 15, "准备下载", "正在启动或复用浏览器")
    task.error = None
    task.logs.append("开始下载书籍到本地")
    save_task_manifest(task)
    uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

    try:
        with contextlib.redirect_stdout(Tee(task)):
            set_task_progress(task, "downloading", 45, "正在下载", "正在打开书籍页面并等待下载")
            save_task_manifest(task)
            downloaded = download_with_preferred_browser(uploader, task.zlibrary_url)
            if not downloaded:
                raise RuntimeError("下载失败，未返回文件")
            downloaded_file, file_format = downloaded
            if not downloaded_file:
                raise RuntimeError("下载失败，未找到文件")
            task.downloaded_file = str(downloaded_file)
            task.final_file = str(downloaded_file)
            task.file_format = file_format
            set_task_progress(task, "downloaded", 90, "保存完成", Path(downloaded_file).name)
            save_task_manifest(task)

        set_task_progress(task, "downloaded", 100, "下载完成", "已保存到本地文件列表")
        task.status = "completed"
        task.logs.append("下载完成，已保存到本地")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "下载失败")
        save_task_manifest(task)


def run_local_upload_task(task: UploadTask) -> None:
    lock = task_operation_lock(task.id)
    if not lock.acquire(blocking=False):
        fail_task(task, "当前文件已有处理或上传任务正在运行", "任务忙碌")
        save_task_manifest(task)
        return

    try:
        task.status = "running"
        set_task_progress(task, "uploading", 15, "准备上传", "正在检查本地文件")
        task.error = None
        task.logs.append("开始上传本地文件")
        save_task_manifest(task)
        uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

        if not task.local_path:
            raise ValueError("请选择本地文件")

        local_file = resolve_safe_local_file(task.local_path, task.workspace_root)
        task.local_path = str(local_file)
        task.downloaded_file = str(local_file)
        task.file_format = local_file.suffix.lower().lstrip(".") or task.file_format

        if not task.notebook_id:
            if not task.notebook_title:
                raise ValueError("请选择知识库或输入新知识库名称")
            set_task_progress(task, "creating_notebook", 20, "创建知识库", task.notebook_title)
            task.logs.append(f"创建知识库: {task.notebook_title}")
            save_task_manifest(task)
            notebook = create_notebook(task.notebook_title)
            task.notebook_id = notebook["id"]
            task.notebook_title = notebook["title"]

        with contextlib.redirect_stdout(Tee(task)):
            upload_files: Path | list[Path]
            if task.parts:
                upload_files = resolve_existing_upload_files(task)
                task.logs.append(f"使用现有处理结果上传 {len(upload_files)} 个来源")
            else:
                final_candidate = None
                if task.final_file:
                    with contextlib.suppress(BadRequest):
                        final_candidate = resolve_safe_local_file(task.final_file, task.workspace_root)
                if final_candidate and final_candidate.resolve() != local_file.resolve():
                    upload_files = final_candidate
                    task.logs.append(f"使用现有处理结果上传: {final_candidate.name}")
                else:
                    set_task_progress(task, "converting", 45, "正在处理", "正在生成可上传来源")
                    save_task_manifest(task)
                    final_file = uploader.convert_to_txt(local_file, task.file_format)
                    record_processed_files(task, final_file)
                    upload_files = final_file
            set_task_progress(task, "uploading", 72, "正在上传", "正在上传本地来源")
            save_task_manifest(task)
            result = uploader.upload_to_notebooklm(upload_files, notebook_id=task.notebook_id)

        record_upload_result(task, result)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "上传失败"))

        set_task_progress(task, "uploaded", 100, "上传完成", task.notebook_title or task.notebook_id or "")
        task.status = "completed"
        task.logs.append("本地文件上传完成")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "上传失败")
        save_task_manifest(task)
    finally:
        lock.release()


def run_process_local_task(task: UploadTask) -> None:
    lock = task_operation_lock(task.id)
    if not lock.acquire(blocking=False):
        fail_task(task, "当前文件已有处理或上传任务正在运行", "任务忙碌")
        save_task_manifest(task)
        return

    try:
        task.status = "running"
        set_task_progress(task, "converting", 20, "准备处理", "正在检查本地文件")
        task.error = None
        task.logs.append("开始处理本地文件")
        save_task_manifest(task)
        uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

        if not task.local_path:
            raise ValueError("请选择本地文件")

        local_file = resolve_safe_local_file(task.local_path, task.workspace_root)
        task.local_path = str(local_file)
        task.downloaded_file = str(local_file)
        task.file_format = local_file.suffix.lower().lstrip(".") or task.file_format

        if task.parts and task.processing_strategy == "keep":
            task.stage = "processed"
            set_task_progress(task, "processed", 100, "已保留分片", "未重新生成处理结果")
            task.status = "completed"
            task.logs.append("已保留现有处理结果")
            save_task_manifest(task)
            return
        if task.parts and task.processing_strategy == "version":
            task.logs.append("生成新版本处理结果，旧上传记录保留为历史")
            local_file_for_processing = create_versioned_processing_input(local_file, task)
        elif task.parts and task.processing_strategy == "replace":
            task.logs.append("覆盖现有处理结果，旧上传记录保留为历史")
            local_file_for_processing = local_file
        else:
            local_file_for_processing = local_file

        with contextlib.redirect_stdout(Tee(task)):
            set_task_progress(task, "converting", 55, "正在处理", "正在转换或分片")
            save_task_manifest(task)
            final_file = uploader.convert_to_txt(local_file_for_processing, task.file_format)
            record_processed_files(task, final_file)

        set_task_progress(task, "processed", 100, "处理完成", "已生成可上传来源")
        task.status = "completed"
        task.logs.append("本地文件处理完成")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "处理失败")
        save_task_manifest(task)
    finally:
        lock.release()


def run_source_upload_task(task: UploadTask) -> None:
    lock = task_operation_lock(task.id)
    if not lock.acquire(blocking=False):
        fail_task(task, "当前文件已有处理或上传任务正在运行", "任务忙碌")
        save_task_manifest(task)
        return

    try:
        task.status = "running"
        set_task_progress(task, "uploading", 20, "准备上传", "正在检查已选来源")
        task.error = None
        task.logs.append("开始上传单个来源")
        save_task_manifest(task)
        uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

        if not task.selected_source_path:
            raise ValueError("请选择要上传的来源")

        source_file = resolve_safe_local_file(task.selected_source_path, task.workspace_root)

        if not task.notebook_id:
            if not task.notebook_title:
                raise ValueError("请选择知识库或输入新知识库名称")
            set_task_progress(task, "creating_notebook", 25, "创建知识库", task.notebook_title)
            task.logs.append(f"创建知识库: {task.notebook_title}")
            save_task_manifest(task)
            notebook = create_notebook(task.notebook_title)
            task.notebook_id = notebook["id"]
            task.notebook_title = notebook["title"]

        with contextlib.redirect_stdout(Tee(task)):
            set_task_progress(task, "uploading", 65, "正在上传", source_file.name)
            save_task_manifest(task)
            result = uploader.upload_to_notebooklm(source_file, notebook_id=task.notebook_id)

        record_single_source_upload_result(task, source_file, result)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "上传失败"))

        set_task_progress(task, "uploaded", 100, "上传完成", source_file.name)
        task.status = "completed"
        task.logs.append(f"单个来源上传完成: {source_file.name}")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "单个来源上传失败")
        save_task_manifest(task)
    finally:
        lock.release()


def run_sources_upload_task(task: UploadTask) -> None:
    lock = task_operation_lock(task.id)
    if not lock.acquire(blocking=False):
        fail_task(task, "当前文件已有处理或上传任务正在运行", "任务忙碌")
        save_task_manifest(task)
        return

    try:
        task.status = "running"
        set_task_progress(task, "uploading", 18, "准备上传", "正在检查已选来源")
        task.error = None
        task.logs.append("开始批量上传已选来源")
        save_task_manifest(task)
        uploader = ZLibraryAutoUploader(task_id=task.id, workspace_root=task.workspace_root)

        source_files = resolve_selected_source_files(task)

        if not task.notebook_id:
            if not task.notebook_title:
                raise ValueError("请选择知识库或输入新知识库名称")
            set_task_progress(task, "creating_notebook", 24, "创建知识库", task.notebook_title)
            task.logs.append(f"创建知识库: {task.notebook_title}")
            save_task_manifest(task)
            notebook = create_notebook(task.notebook_title)
            task.notebook_id = notebook["id"]
            task.notebook_title = notebook["title"]

        with contextlib.redirect_stdout(Tee(task)):
            set_task_progress(task, "uploading", 68, "正在上传", f"{len(source_files)} 个来源")
            save_task_manifest(task)
            result = uploader.upload_to_notebooklm(source_files, notebook_id=task.notebook_id)

        record_sources_upload_result(task, source_files, result)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "上传失败"))

        set_task_progress(task, "uploaded", 100, "上传完成", f"{len(source_files)} 个来源")
        task.status = "completed"
        task.logs.append(f"已选来源上传完成: {len(source_files)} 个")
        save_task_manifest(task)
    except Exception as exc:
        fail_task(task, exc, "已选来源上传失败")
        save_task_manifest(task)
    finally:
        lock.release()


def start_upload_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_upload_task, args=(task,), daemon=True)
    thread.start()


def start_download_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_download_task, args=(task,), daemon=True)
    thread.start()


def start_local_upload_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_local_upload_task, args=(task,), daemon=True)
    thread.start()


def start_process_local_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_process_local_task, args=(task,), daemon=True)
    thread.start()


def start_source_upload_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_source_upload_task, args=(task,), daemon=True)
    thread.start()


def start_sources_upload_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_sources_upload_task, args=(task,), daemon=True)
    thread.start()


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BadRequest("请求体不是有效 JSON") from exc


def resolve_static_file(path: str, base: Path) -> Path:
    base = base.resolve()
    relative = "index.html" if path in ("", "/") else path.lstrip("/")
    file_path = (base / relative).resolve()

    try:
        file_path.relative_to(base)
    except ValueError:
        return base / "index.html"

    if not file_path.exists():
        return base / "index.html"
    return file_path


def parse_server_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="web_api.py",
        description="Z-Library to NotebookLM Web Workbench API",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=7860, help="监听端口，默认 7860")
    return parser.parse_args(argv)


class WorkbenchHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/status":
                json_response(self, 200, get_auth_status())
                return

            if parsed.path == "/api/browser/status":
                json_response(self, 200, get_browser_status())
                return

            if parsed.path == "/api/search":
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                limit = parse_search_limit(params)
                if not query:
                    json_response(self, 400, {"error": "搜索关键词不能为空"})
                    return
                results = search_zlibrary_managed(query, limit=limit)
                json_response(self, 200, {"results": results})
                return

            if parsed.path == "/api/notebooks":
                json_response(self, 200, {"notebooks": list_notebooks()})
                return

            if parsed.path == "/api/local-files":
                json_response(self, 200, {"assets": scan_local_assets()})
                return

            if parsed.path == "/api/tasks":
                tasks_by_id: dict[str, UploadTask] = {}
                for task in scan_task_manifests():
                    tasks_by_id[task.id] = task
                with TASKS_LOCK:
                    for task in TASKS.values():
                        tasks_by_id[task.id] = task
                    tasks = list(tasks_by_id.values())
                tasks.sort(key=lambda item: item.updated_at, reverse=True)
                json_response(self, 200, {"tasks": [serialize_task(task) for task in tasks]})
                return

            if parsed.path.startswith("/api/tasks/"):
                task_id = parsed.path.rsplit("/", 1)[-1]
                with TASKS_LOCK:
                    task = TASKS.get(task_id)
                if not task:
                    task = load_task_from_manifest(task_id)
                if not task:
                    json_response(self, 404, {"error": "任务不存在"})
                    return
                json_response(self, 200, serialize_task(task))
                return

            self.serve_static(parsed.path)
        except BadRequest as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/zlibrary/start":
                start_zlibrary_login()
                json_response(self, 202, get_auth_status(probe_notebooklm=False))
                return

            if parsed.path == "/api/browser/start":
                body = read_json_body(self)
                headless = bool(body.get("headless", True))
                keep_open = bool(body.get("keep_open", True))
                timeout = body.get("idle_timeout_seconds")
                idle_timeout_seconds = int(timeout) if timeout is not None else None
                json_response(self, 202, start_managed_browser(headless=headless, keep_open=keep_open, idle_timeout_seconds=idle_timeout_seconds))
                return

            if parsed.path == "/api/browser/close":
                body = read_json_body(self)
                force = bool(body.get("force", False))
                json_response(self, 200, close_managed_browser(force=force))
                return

            if parsed.path == "/api/browser/restart":
                body = read_json_body(self)
                headless = bool(body.get("headless", True))
                keep_open = bool(body.get("keep_open", True))
                json_response(self, 202, restart_managed_browser(headless=headless, keep_open=keep_open))
                return

            if parsed.path == "/api/auth/zlibrary/complete":
                complete_zlibrary_login()
                json_response(self, 202, get_auth_status(probe_notebooklm=False))
                return

            if parsed.path == "/api/auth/zlibrary/cancel":
                cancel_zlibrary_login()
                json_response(self, 200, get_auth_status(probe_notebooklm=False))
                return

            if parsed.path == "/api/auth/notebooklm/start":
                start_notebooklm_login()
                json_response(self, 202, get_auth_status())
                return

            if parsed.path == "/api/auth/notebooklm/cancel":
                cancel_notebooklm_login()
                json_response(self, 200, get_auth_status(probe_notebooklm=False))
                return

            if parsed.path == "/api/notebooks":
                body = read_json_body(self)
                title = str(body.get("title", "")).strip()
                if not title:
                    json_response(self, 400, {"error": "知识库名称不能为空"})
                    return
                json_response(self, 201, {"notebook": create_notebook(title)})
                return

            if parsed.path == "/api/upload":
                body = read_json_body(self)
                zlibrary_url = str(body.get("zlibrary_url", "")).strip()
                notebook_id = str(body.get("notebook_id", "")).strip() or None
                notebook_title = str(body.get("notebook_title", "")).strip() or None
                if not zlibrary_url:
                    json_response(self, 400, {"error": "Z-Library 链接不能为空"})
                    return
                if not notebook_id and not notebook_title:
                    json_response(self, 400, {"error": "请选择知识库或输入新知识库名称"})
                    return
                task = create_task(zlibrary_url, notebook_id=notebook_id, notebook_title=notebook_title)
                start_upload_task(task)
                json_response(self, 202, serialize_task(task))
                return

            if parsed.path == "/api/download":
                body = read_json_body(self)
                zlibrary_url = str(body.get("zlibrary_url", "")).strip()
                if not zlibrary_url:
                    json_response(self, 400, {"error": "Z-Library 链接不能为空"})
                    return
                task = create_download_task(zlibrary_url)
                start_download_task(task)
                json_response(self, 202, serialize_task(task))
                return

            if parsed.path == "/api/upload-local":
                body = read_json_body(self)
                local_path = str(body.get("local_path", "")).strip()
                notebook_id = str(body.get("notebook_id", "")).strip() or None
                notebook_title = str(body.get("notebook_title", "")).strip() or None
                task_id = str(body.get("task_id", "")).strip() or None
                if not local_path:
                    json_response(self, 400, {"error": "请选择本地文件"})
                    return
                if not notebook_id and not notebook_title:
                    json_response(self, 400, {"error": "请选择知识库或输入新知识库名称"})
                    return
                task = create_local_upload_task(local_path, notebook_id=notebook_id, notebook_title=notebook_title, task_id=task_id)
                start_local_upload_task(task)
                json_response(self, 202, serialize_task(task))
                return

            if parsed.path == "/api/upload-source":
                body = read_json_body(self)
                source_path = str(body.get("source_path", "")).strip()
                notebook_id = str(body.get("notebook_id", "")).strip() or None
                notebook_title = str(body.get("notebook_title", "")).strip() or None
                task_id = str(body.get("task_id", "")).strip() or None
                if not source_path:
                    json_response(self, 400, {"error": "请选择要上传的来源"})
                    return
                if not notebook_id and not notebook_title:
                    json_response(self, 400, {"error": "请选择知识库或输入新知识库名称"})
                    return
                task = create_source_upload_task(source_path, notebook_id=notebook_id, notebook_title=notebook_title, task_id=task_id)
                start_source_upload_task(task)
                json_response(self, 202, serialize_task(task))
                return

            if parsed.path == "/api/upload-sources":
                body = read_json_body(self)
                raw_source_paths = body.get("source_paths") or []
                notebook_id = str(body.get("notebook_id", "")).strip() or None
                notebook_title = str(body.get("notebook_title", "")).strip() or None
                task_id = str(body.get("task_id", "")).strip() or None
                if not isinstance(raw_source_paths, list):
                    json_response(self, 400, {"error": "来源列表必须是数组"})
                    return
                source_paths = [str(source_path).strip() for source_path in raw_source_paths if str(source_path).strip()]
                if not source_paths:
                    json_response(self, 400, {"error": "请选择要上传的来源"})
                    return
                if not notebook_id and not notebook_title:
                    json_response(self, 400, {"error": "请选择知识库或输入新知识库名称"})
                    return
                task = create_sources_upload_task(source_paths, notebook_id=notebook_id, notebook_title=notebook_title, task_id=task_id)
                start_sources_upload_task(task)
                json_response(self, 202, serialize_task(task))
                return

            if parsed.path == "/api/process-local":
                body = read_json_body(self)
                local_path = str(body.get("local_path", "")).strip()
                task_id = str(body.get("task_id", "")).strip() or None
                strategy = str(body.get("strategy", "")).strip() or None
                if not local_path:
                    json_response(self, 400, {"error": "请选择本地文件"})
                    return
                task = create_process_local_task(local_path, task_id=task_id, strategy=strategy)
                start_process_local_task(task)
                json_response(self, 202, serialize_task(task))
                return

            json_response(self, 404, {"error": "接口不存在"})
        except BadRequest as exc:
            json_response(self, 400, {"error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def serve_static(self, path: str) -> None:
        base = WEB_DIST_DIR if WEB_DIST_DIR.exists() else WEB_PUBLIC_DIR
        file_path = resolve_static_file(path, base)

        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".svg":
            content_type = "image/svg+xml"

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), WorkbenchHandler)
    actual_host, actual_port = server.server_address
    print("Z-Library to NotebookLM Web Workbench")
    print(f"打开: http://{actual_host}:{actual_port}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> None:
    args = parse_server_args(argv)
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
