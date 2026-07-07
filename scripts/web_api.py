#!/usr/bin/env python3
"""
Local web API for the Z-Library to NotebookLM workbench.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import subprocess
import sys
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

from scripts.search import search_zlibrary
from scripts.upload import ZLibraryAutoUploader
from scripts.browser import choose_chromium_launch_options, choose_system_browser_channel


WEB_DIST_DIR = ROOT_DIR / "web" / "dist"
WEB_PUBLIC_DIR = ROOT_DIR / "web"
ZLIBRARY_LOGIN_TIMEOUT_SECONDS = 15 * 60
DEFAULT_SEARCH_LIMIT = 50
MAX_SEARCH_LIMIT = 80
TASKS: dict[str, "UploadTask"] = {}
TASKS_LOCK = threading.Lock()
ZLIBRARY_LOGIN_LOCK = threading.RLock()
ZLIBRARY_LOGIN_SESSION: "ZLibraryLoginSession | None" = None
NOTEBOOKLM_LOGIN_LOCK = threading.RLock()
NOTEBOOKLM_LOGIN_PROCESS: subprocess.Popen[str] | None = None
NOTEBOOKLM_STATUS_CACHE_LOCK = threading.Lock()
NOTEBOOKLM_STATUS_CACHE: dict[str, Any] | None = None


class BadRequest(ValueError):
    pass


@dataclass
class UploadTask:
    id: str
    zlibrary_url: str
    notebook_id: str | None = None
    notebook_title: str | None = None
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None


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
    return task


def serialize_task(task: UploadTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "zlibrary_url": task.zlibrary_url,
        "notebook_id": task.notebook_id,
        "notebook_title": task.notebook_title,
        "status": task.status,
        "logs": task.logs,
        "result": task.result,
        "error": task.error,
    }


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


class Tee(io.StringIO):
    def __init__(self, task: UploadTask):
        super().__init__()
        self.task = task

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.task.logs.append(line)
        return len(text)


def run_upload_task(task: UploadTask) -> None:
    task.status = "running"
    task.logs.append("开始下载书籍")
    uploader = ZLibraryAutoUploader(task_id=task.id)

    try:
        if not task.notebook_id:
            if not task.notebook_title:
                raise ValueError("请选择知识库或输入新知识库名称")
            task.logs.append(f"创建知识库: {task.notebook_title}")
            notebook = create_notebook(task.notebook_title)
            task.notebook_id = notebook["id"]
            task.notebook_title = notebook["title"]

        with contextlib.redirect_stdout(Tee(task)):
            downloaded = asyncio.run(uploader.download_from_zlibrary(task.zlibrary_url))
            if not downloaded:
                raise RuntimeError("下载失败，未返回文件")

            downloaded_file, file_format = downloaded
            if not downloaded_file:
                raise RuntimeError("下载失败，未找到文件")

            final_file = uploader.convert_to_txt(downloaded_file, file_format)
            result = uploader.upload_to_notebooklm(final_file, notebook_id=task.notebook_id)

        if not result.get("success"):
            raise RuntimeError(result.get("error", "上传失败"))

        task.result = result
        task.status = "completed"
        task.logs.append("上传完成")
    except Exception as exc:
        task.error = str(exc)
        task.status = "failed"
        task.logs.append(f"失败: {exc}")


def start_upload_task(task: UploadTask) -> None:
    thread = threading.Thread(target=run_upload_task, args=(task,), daemon=True)
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


class WorkbenchHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/auth/status":
                json_response(self, 200, get_auth_status())
                return

            if parsed.path == "/api/search":
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                limit = parse_search_limit(params)
                if not query:
                    json_response(self, 400, {"error": "搜索关键词不能为空"})
                    return
                results = asyncio.run(search_zlibrary(query, limit=limit))
                json_response(self, 200, {"results": [result.__dict__ for result in results]})
                return

            if parsed.path == "/api/notebooks":
                json_response(self, 200, {"notebooks": list_notebooks()})
                return

            if parsed.path.startswith("/api/tasks/"):
                task_id = parsed.path.rsplit("/", 1)[-1]
                with TASKS_LOCK:
                    task = TASKS.get(task_id)
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


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 7860), WorkbenchHandler)
    print("Z-Library to NotebookLM Web Workbench")
    print("打开: http://127.0.0.1:7860")
    server.serve_forever()


if __name__ == "__main__":
    main()
