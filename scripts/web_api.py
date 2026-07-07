#!/usr/bin/env python3
"""
Local web API for the Z-Library to NotebookLM workbench.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import subprocess
import sys
import threading
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


WEB_DIST_DIR = ROOT_DIR / "web" / "dist"
WEB_PUBLIC_DIR = ROOT_DIR / "web"
TASKS: dict[str, "UploadTask"] = {}
TASKS_LOCK = threading.Lock()


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


def run_notebooklm(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["notebooklm", *args],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 notebooklm 命令，请先安装并运行 notebooklm login") from exc


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
    uploader = ZLibraryAutoUploader()

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
            if parsed.path == "/api/search":
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0].strip()
                limit = int(params.get("limit", ["10"])[0])
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
