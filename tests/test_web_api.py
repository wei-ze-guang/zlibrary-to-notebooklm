import json
import subprocess
import tempfile
import threading
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from scripts.web_api import (
    BadRequest,
    cancel_notebooklm_login,
    choose_chromium_launch_options,
    close_managed_browser,
    create_download_task,
    create_local_upload_task,
    create_process_local_task,
    create_source_upload_task,
    create_sources_upload_task,
    create_task,
    canonical_zlibrary_key,
    format_zlibrary_login_error,
    get_auth_status,
    get_browser_status,
    get_notebooklm_auth_status,
    get_zlibrary_auth_status,
    load_task_from_manifest,
    parse_created_notebook,
    parse_notebooks,
    parse_server_args,
    parse_search_limit,
    read_json_body,
    resolve_notebooklm_command,
    resolve_safe_local_file,
    resolve_unique_workspace_file,
    resolve_workspace_download_folder,
    resolve_static_file,
    run_download_task,
    run_local_upload_task,
    run_process_local_task,
    run_source_upload_task,
    run_sources_upload_task,
    run_upload_task,
    run_notebooklm,
    save_task_manifest,
    scan_local_assets,
    scan_task_manifests,
    search_zlibrary_managed,
    serialize_task,
    start_managed_browser,
    start_notebooklm_login,
    task_manifest_path,
)


class WebApiTest(unittest.TestCase):
    def tearDown(self):
        with patch("scripts.web_api.time.time", return_value=10_000.0):
            close_managed_browser(force=True)

    def test_managed_browser_starts_once_and_reports_running_status(self):
        start_calls = []

        class FakeContext:
            def __init__(self):
                self.closed = False
                self.pages = []

            def is_closed(self):
                return self.closed

            def close(self):
                self.closed = True

        class FakeManager:
            def __enter__(self):
                return type("PW", (), {
                    "chromium": type("Chromium", (), {
                        "launch_persistent_context": lambda _self, *args, **kwargs: start_calls.append(kwargs) or FakeContext()
                    })()
                })()

            def __exit__(self, *_args):
                return False

        with patch("scripts.web_api.sync_playwright_factory", return_value=FakeManager()):
            with patch("scripts.web_api.choose_chromium_launch_options", return_value=type("Choice", (), {"log": "using chrome", "options": {}})()):
                first = start_managed_browser(headless=True)
                second = start_managed_browser(headless=True)
                status = get_browser_status()

        self.assertEqual(len(start_calls), 1)
        self.assertEqual(first["status"], "running")
        self.assertEqual(second["status"], "running")
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["active_operations"], 0)
        self.assertTrue(start_calls[0]["headless"])

    def test_managed_browser_refuses_non_force_close_when_busy(self):
        class FakeContext:
            pages = []

            def is_closed(self):
                return False

            def close(self):
                pass

        class FakeManager:
            def __enter__(self):
                return type("PW", (), {
                    "chromium": type("Chromium", (), {
                        "launch_persistent_context": lambda _self, *args, **kwargs: FakeContext()
                    })()
                })()

            def __exit__(self, *_args):
                return False

        with patch("scripts.web_api.sync_playwright_factory", return_value=FakeManager()):
            with patch("scripts.web_api.choose_chromium_launch_options", return_value=type("Choice", (), {"log": None, "options": {}})()):
                start_managed_browser(headless=True)
                with patch("scripts.web_api.MANAGED_BROWSER.active_operations", 1):
                    with self.assertRaisesRegex(BadRequest, "正在使用"):
                        close_managed_browser(force=False)

    def test_managed_browser_force_close_releases_context(self):
        closed = []

        class FakeContext:
            pages = []

            def is_closed(self):
                return False

            def close(self):
                closed.append(True)

        class FakeManager:
            def __enter__(self):
                return type("PW", (), {
                    "chromium": type("Chromium", (), {
                        "launch_persistent_context": lambda _self, *args, **kwargs: FakeContext()
                    })()
                })()

            def __exit__(self, *_args):
                closed.append("playwright")
                return False

        with patch("scripts.web_api.sync_playwright_factory", return_value=FakeManager()):
            with patch("scripts.web_api.choose_chromium_launch_options", return_value=type("Choice", (), {"log": None, "options": {}})()):
                start_managed_browser(headless=True)
                status = close_managed_browser(force=True)

        self.assertEqual(status["status"], "stopped")
        self.assertIn(True, closed)
        self.assertIn("playwright", closed)

    def test_managed_browser_idle_timeout_closes_context(self):
        closed = []

        class FakeContext:
            pages = []

            def is_closed(self):
                return False

            def close(self):
                closed.append(True)

        class FakeManager:
            def __enter__(self):
                return type("PW", (), {
                    "chromium": type("Chromium", (), {
                        "launch_persistent_context": lambda _self, *args, **kwargs: FakeContext()
                    })()
                })()

            def __exit__(self, *_args):
                return False

        with patch("scripts.web_api.sync_playwright_factory", return_value=FakeManager()):
            with patch("scripts.web_api.choose_chromium_launch_options", return_value=type("Choice", (), {"log": None, "options": {}})()):
                with patch("scripts.web_api.time.time", return_value=100.0):
                    start_managed_browser(headless=True, idle_timeout_seconds=10)
            with patch("scripts.web_api.time.time", return_value=111.0):
                status = get_browser_status()

        self.assertEqual(status["status"], "idle_timeout")
        self.assertEqual(closed, [True])

    def test_managed_browser_runs_search_operations_on_browser_thread(self):
        calls = []

        class FakePage:
            def __init__(self, owner_thread):
                self.owner_thread = owner_thread

            def _check_thread(self):
                if threading.get_ident() != self.owner_thread:
                    raise RuntimeError("cannot switch to a different thread (which happens to have exited)")

            def set_default_timeout(self, _timeout):
                self._check_thread()

            def goto(self, *_args, **_kwargs):
                self._check_thread()
                calls.append(("goto", threading.get_ident()))

            def wait_for_load_state(self, *_args, **_kwargs):
                self._check_thread()

            def content(self):
                self._check_thread()
                return "<html></html>"

            def close(self):
                self._check_thread()

        class FakeContext:
            pages = []

            def __init__(self):
                self.owner_thread = threading.get_ident()

            def is_closed(self):
                return False

            def new_page(self):
                return FakePage(self.owner_thread)

            def close(self):
                pass

        class FakeManager:
            def __enter__(self):
                return type("PW", (), {
                    "chromium": type("Chromium", (), {
                        "launch_persistent_context": lambda _self, *args, **kwargs: FakeContext()
                    })()
                })()

            def __exit__(self, *_args):
                return False

        errors = []

        def run_search():
            try:
                search_zlibrary_managed("os", limit=1)
            except Exception as exc:
                errors.append(str(exc))

        with patch("scripts.web_api.zlibrary_storage_state_path", return_value=Path(__file__)):
            with patch("scripts.web_api.extract_search_results", return_value=[]):
                with patch("scripts.web_api.sync_playwright_factory", return_value=FakeManager()):
                    with patch("scripts.web_api.choose_chromium_launch_options", return_value=type("Choice", (), {"log": None, "options": {}})()):
                        start_managed_browser(headless=True)
                        first = threading.Thread(target=run_search)
                        second = threading.Thread(target=run_search)
                        first.start()
                        first.join()
                        second.start()
                        second.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 2)
        self.assertEqual(len({thread_id for _name, thread_id in calls}), 1)

    def test_parse_notebooks_accepts_list_payload(self):
        payload = json.dumps([
            {"id": "abc123", "title": "Operating Systems"},
            {"notebook_id": "def456", "name": "Algorithms"},
        ])

        notebooks = parse_notebooks(payload)

        self.assertEqual(notebooks[0]["id"], "abc123")
        self.assertEqual(notebooks[0]["title"], "Operating Systems")
        self.assertEqual(notebooks[1]["id"], "def456")
        self.assertEqual(notebooks[1]["title"], "Algorithms")

    def test_parse_notebooks_accepts_nested_payload(self):
        payload = json.dumps({
            "notebooks": [
                {"id": "abc123", "title": "Operating Systems"},
            ]
        })

        notebooks = parse_notebooks(payload)

        self.assertEqual(notebooks, [{"id": "abc123", "title": "Operating Systems"}])

    def test_parse_notebooks_skips_malformed_items(self):
        payload = json.dumps([
            {"id": "abc123", "title": "Operating Systems"},
            "not a notebook",
            {"title": "Missing ID"},
        ])

        notebooks = parse_notebooks(payload)

        self.assertEqual(notebooks, [{"id": "abc123", "title": "Operating Systems"}])

    def test_parse_created_notebook_accepts_nested_notebook(self):
        payload = json.dumps({"notebook": {"id": "abc123", "title": "New Notebook"}})

        notebook = parse_created_notebook(payload)

        self.assertEqual(notebook["id"], "abc123")
        self.assertEqual(notebook["title"], "New Notebook")

    def test_parse_search_limit_defaults_and_clamps(self):
        self.assertEqual(parse_search_limit({}), 50)
        self.assertEqual(parse_search_limit({"limit": ["12"]}), 12)
        self.assertEqual(parse_search_limit({"limit": ["999"]}), 80)

    def test_parse_search_limit_rejects_invalid_values(self):
        with self.assertRaises(BadRequest):
            parse_search_limit({"limit": ["abc"]})

        with self.assertRaises(BadRequest):
            parse_search_limit({"limit": ["0"]})

    def test_parse_server_args_defaults_to_local_workbench_port(self):
        args = parse_server_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 7860)

    def test_parse_server_args_accepts_host_and_port_for_extension(self):
        args = parse_server_args(["--host", "127.0.0.1", "--port", "51234"])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 51234)

    def test_create_task_defaults_to_queued_status(self):
        task = create_task("https://zh.zlib.li/book/example", notebook_title="OS Notes")

        self.assertEqual(task.status, "queued")
        self.assertIn("任务已创建", task.logs[0])

    def test_serialize_task_exposes_upload_result(self):
        task = create_task("https://zh.zlib.li/book/example", notebook_id="abc123")
        task.status = "completed"
        task.result = {"notebook_id": "abc123", "source_ids": ["src1"]}

        data = serialize_task(task)

        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["result"]["source_ids"], ["src1"])

    def test_task_manifest_path_uses_task_workspace(self):
        path = task_manifest_path("task/42", workspace_root=Path("/tmp/tasks"))

        self.assertEqual(path, Path("/tmp/tasks/task-42/manifest.json"))

    def test_load_task_from_manifest_restores_task_after_backend_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = create_download_task("https://zh.zlib.li/book/example", workspace_root=root)
            task.id = "task-1"
            task.status = "failed"
            task.stage = "failed"
            task.error = "下载失败，未找到文件"
            task.progress = {"phase": "failed", "percent": 100, "label": "下载失败", "detail": task.error}
            save_task_manifest(task)

            restored = load_task_from_manifest("task-1", workspace_root=root)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.id, "task-1")
        self.assertEqual(restored.status, "failed")
        self.assertEqual(restored.stage, "failed")
        self.assertEqual(restored.progress["label"], "下载失败")
        self.assertEqual(restored.error, "下载失败，未找到文件")

    def test_scan_task_manifests_includes_failed_download_without_local_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = create_download_task("https://zh.zlib.li/book/example", workspace_root=root)
            task.status = "failed"
            task.stage = "failed"
            task.error = "下载失败，未找到文件"
            task.progress = {"phase": "failed", "percent": 100, "label": "下载失败", "detail": task.error}
            save_task_manifest(task)

            tasks = scan_task_manifests(root)
            assets = scan_local_assets(root)

        self.assertEqual([item.id for item in tasks], [task.id])
        self.assertEqual(tasks[0].status, "failed")
        self.assertEqual(assets, [])

    def test_canonical_zlibrary_key_uses_stable_book_path(self):
        first = canonical_zlibrary_key("https://zh.zlib.li/book/12345/some-title?token=abc#download")
        second = canonical_zlibrary_key("https://z-library.sk/book/12345/some-title")

        self.assertEqual(first, "book/12345/some-title")
        self.assertEqual(second, first)

    def test_download_task_serializes_progress(self):
        task = create_download_task("https://zh.zlib.li/book/example")

        data = serialize_task(task)

        self.assertEqual(data["book_key"], "book/example")
        self.assertEqual(data["progress"]["phase"], "queued")
        self.assertEqual(data["progress"]["percent"], 0)

    def test_scan_local_assets_reads_manifest_and_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "task-1"
            downloads = task_dir / "downloads"
            downloads.mkdir(parents=True)
            downloaded = downloads / "book.pdf"
            downloaded.write_bytes(b"pdf")
            manifest = {
                "id": "task-1",
                "mode": "remote",
                "zlibrary_url": "https://zh.zlib.li/book/example",
                "notebook_id": "nb123",
                "status": "failed",
                "stage": "upload",
                "downloaded_file": str(downloaded),
                "final_file": str(downloaded),
                "file_format": "pdf",
                "error": "NotebookLM timeout",
                "result": {"success": False},
                "updated_at": 123.0,
            }
            (task_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            assets = scan_local_assets(root)

        self.assertEqual(len(assets), 1)
        asset = assets[0]
        self.assertEqual(asset["task_id"], "task-1")
        self.assertEqual(asset["filename"], "book.pdf")
        self.assertEqual(asset["extension"], "pdf")
        self.assertEqual(asset["size"], 3)
        self.assertEqual(asset["status"], "failed")
        self.assertEqual(asset["stage"], "upload")
        self.assertEqual(asset["error"], "NotebookLM timeout")
        self.assertEqual(asset["notebook_id"], "nb123")
        self.assertEqual(asset["book_key"], "book/example")
        self.assertEqual(asset["local_path"], str(downloaded.resolve()))
        self.assertEqual(asset["upload_summary"]["total"], 1)
        self.assertEqual(asset["upload_summary"]["failed"], 1)
        self.assertEqual(asset["upload_sources"][0]["kind"], "file")
        self.assertEqual(asset["upload_sources"][0]["status"], "failed")

    def test_scan_local_assets_includes_parts_and_uploads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "task-1"
            downloads = task_dir / "downloads"
            parts_dir = task_dir / "books" / "book" / "parts"
            downloads.mkdir(parents=True)
            parts_dir.mkdir(parents=True)
            downloaded = downloads / "book.epub"
            part = parts_dir / "book_part_001_of_001.md"
            downloaded.write_bytes(b"epub")
            part.write_text("part", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "mode": "remote",
                "zlibrary_url": "https://zh.zlib.li/book/example",
                "notebook_id": "nb123",
                "notebook_title": "OS Notes",
                "status": "completed",
                "stage": "uploaded",
                "downloaded_file": str(downloaded),
                "final_file": str(part),
                "file_format": "epub",
                "parts": [{"index": 1, "path": str(part), "filename": part.name, "status": "uploaded", "source_id": "src1"}],
                "uploads": [{"status": "completed", "notebook_id": "nb123", "source_ids": ["src1"]}],
                "updated_at": 123.0,
            }
            (task_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            assets = scan_local_assets(root)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["original_file"]["path"], str(downloaded.resolve()))
        self.assertEqual(assets[0]["processed_file"]["path"], str(part.resolve()))
        self.assertEqual(assets[0]["parts"][0]["source_id"], "src1")
        self.assertEqual(assets[0]["upload_sources"][0]["kind"], "part")
        self.assertEqual(assets[0]["upload_sources"][0]["status"], "uploaded")
        self.assertEqual(assets[0]["upload_summary"]["uploaded"], 1)
        self.assertEqual(assets[0]["uploads"][0]["source_ids"], ["src1"])

    def test_scan_local_assets_exposes_single_processed_file_as_upload_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "task-1"
            downloads = task_dir / "downloads"
            downloads.mkdir(parents=True)
            downloaded = downloads / "book.pdf"
            downloaded.write_bytes(b"pdf")
            manifest = {
                "id": "task-1",
                "mode": "download",
                "zlibrary_url": "https://zh.zlib.li/book/example",
                "status": "completed",
                "stage": "processed",
                "downloaded_file": str(downloaded),
                "final_file": str(downloaded),
                "file_format": "pdf",
                "updated_at": 123.0,
            }
            (task_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            assets = scan_local_assets(root)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["upload_summary"], {
            "total": 1,
            "uploaded": 0,
            "failed": 0,
            "uploading": 0,
            "ready": 1,
            "state": "ready",
        })
        self.assertEqual(assets[0]["upload_sources"][0]["filename"], "book.pdf")
        self.assertEqual(assets[0]["upload_sources"][0]["status"], "ready")

    def test_resolve_safe_local_file_rejects_paths_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task_dir = root / "task-1" / "downloads"
            task_dir.mkdir(parents=True)
            local_file = task_dir / "book.pdf"
            local_file.write_text("pdf", encoding="utf-8")
            sibling = root.parent / "book.pdf"

            self.assertEqual(resolve_safe_local_file(str(local_file), root), local_file.resolve())
            with self.assertRaises(BadRequest):
                resolve_safe_local_file(str(sibling), root)

    def test_create_local_upload_task_records_local_path_and_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.pdf"
            local_file.parent.mkdir(parents=True)
            local_file.write_text("pdf", encoding="utf-8")

            task = create_local_upload_task(str(local_file), notebook_id="nb123", notebook_title=None, workspace_root=root)

        self.assertEqual(task.mode, "local")
        self.assertEqual(task.local_path, str(local_file.resolve()))
        self.assertEqual(task.notebook_id, "nb123")
        self.assertIn("本地文件上传任务已创建", task.logs[0])

    def test_run_upload_task_keeps_downloaded_file_when_upload_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloaded = root / "task-1" / "downloads" / "book.pdf"
            downloaded.parent.mkdir(parents=True)
            downloaded.write_text("pdf", encoding="utf-8")
            task = create_task("https://zh.zlib.li/book/example", notebook_id="nb123")
            task.id = "task-1"
            task.workspace_root = root
            upload_calls = []

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                async def download_from_zlibrary(self, _url):
                    return downloaded, "pdf"

                def convert_to_txt(self, file_path, file_format):
                    return file_path

                def upload_to_notebooklm(self, _file_path, notebook_id=None):
                    upload_calls.append(notebook_id)
                    return {"success": False, "error": "NotebookLM CLI timeout"}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_upload_task(task)

            manifest = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.status, "failed")
        self.assertEqual(task.error, "NotebookLM CLI timeout")
        self.assertEqual(task.downloaded_file, str(downloaded))
        self.assertEqual(task.final_file, str(downloaded))
        self.assertEqual(upload_calls, ["nb123"])
        self.assertEqual(manifest["downloaded_file"], str(downloaded))
        self.assertEqual(manifest["error"], "NotebookLM CLI timeout")

    def test_run_download_task_records_downloaded_asset_without_uploading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloaded = root / "task-1" / "downloads" / "book.pdf"
            downloaded.parent.mkdir(parents=True)
            downloaded.write_text("pdf", encoding="utf-8")
            task = create_download_task("https://zh.zlib.li/book/example", workspace_root=root)
            task.id = "task-1"

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                async def download_from_zlibrary(self, _url):
                    return downloaded, "pdf"

                def upload_to_notebooklm(self, *_args, **_kwargs):
                    raise AssertionError("download-only task must not upload")

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_download_task(task)

            manifest = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.stage, "downloaded")
        self.assertEqual(task.downloaded_file, str(downloaded))
        self.assertEqual(manifest["downloaded_file"], str(downloaded))
        self.assertEqual(manifest["mode"], "download")

    def test_run_download_task_marks_progress_failed_when_download_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = create_download_task("https://zh.zlib.li/book/example", workspace_root=root)
            task.id = "task-1"

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                with patch("scripts.web_api.download_with_preferred_browser", return_value=(None, None)):
                    run_download_task(task)

            manifest = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.status, "failed")
        self.assertEqual(task.stage, "failed")
        self.assertEqual(task.progress["phase"], "failed")
        self.assertEqual(task.progress["label"], "下载失败")
        self.assertIn("下载失败", task.progress["detail"])
        self.assertEqual(manifest["progress"]["phase"], "failed")

    def test_resolve_workspace_download_folder_creates_safe_project_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            folder = resolve_workspace_download_folder(root, "zlibrary-downloads")

            self.assertEqual(folder, (root / "zlibrary-downloads").resolve())
            self.assertTrue(folder.is_dir())

    def test_resolve_workspace_download_folder_rejects_unsafe_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "zlibrary-downloads").write_text("file collision", encoding="utf-8")

            with self.assertRaisesRegex(BadRequest, "不是文件夹"):
                resolve_workspace_download_folder(root, "zlibrary-downloads")

            with self.assertRaisesRegex(BadRequest, "不能包含"):
                resolve_workspace_download_folder(root, "../outside")

            with self.assertRaisesRegex(BadRequest, "不能是绝对路径"):
                resolve_workspace_download_folder(root, str(root / "absolute"))

    def test_resolve_unique_workspace_file_versions_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "book.pdf").write_text("old", encoding="utf-8")

            target = resolve_unique_workspace_file(folder, "book.pdf")

        self.assertEqual(target.name, "book (1).pdf")

    def test_run_download_task_can_save_original_file_to_vscode_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "tasks"
            project = Path(temp_dir) / "project"
            project.mkdir()
            downloaded = root / "task-1" / "downloads" / "book.pdf"
            downloaded.parent.mkdir(parents=True)
            downloaded.write_text("pdf", encoding="utf-8")
            task = create_download_task(
                "https://zh.zlib.li/book/example",
                workspace_root=root,
                target_workspace_root=str(project),
                target_folder_name="zlibrary-downloads",
            )
            task.id = "task-1"

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                async def download_from_zlibrary(self, _url):
                    return downloaded, "pdf"

                def convert_to_txt(self, *_args, **_kwargs):
                    raise AssertionError("download task must not convert")

                def upload_to_notebooklm(self, *_args, **_kwargs):
                    raise AssertionError("download task must not upload")

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_download_task(task)

            saved = project / "zlibrary-downloads" / "book.pdf"
            manifest = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

            self.assertTrue(saved.exists())
            self.assertEqual(saved.read_text(encoding="utf-8"), "pdf")
            self.assertEqual(task.status, "completed")
            self.assertEqual(task.final_file, str(saved.resolve()))
            self.assertEqual(task.result["workspace_saved_file"], str(saved.resolve()))
            self.assertEqual(manifest["target_workspace_root"], str(project.resolve()))
            self.assertEqual(manifest["result"]["workspace_folder"], str(saved.parent.resolve()))

    def test_run_local_upload_task_uploads_without_downloading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.pdf"
            local_file.parent.mkdir(parents=True)
            local_file.write_text("pdf", encoding="utf-8")
            task = create_local_upload_task(str(local_file), notebook_id="nb123", notebook_title=None, workspace_root=root)

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, file_path, file_format=None):
                    return file_path

                def upload_to_notebooklm(self, file_path, notebook_id=None):
                    return {"success": True, "source_id": "src123", "notebook_id": notebook_id, "title": Path(file_path).stem}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_local_upload_task(task)

            manifest = json.loads(task_manifest_path(task.id, root).read_text(encoding="utf-8"))

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.stage, "uploaded")
        self.assertEqual(task.result["source_id"], "src123")
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["result"]["source_id"], "src123")

    def test_run_local_upload_task_records_parts_and_upload_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part1 = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_002.md"
            part2 = root / "task-1" / "books" / "book" / "parts" / "book_part_002_of_002.md"
            local_file.parent.mkdir(parents=True)
            part1.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part1.write_text("part1", encoding="utf-8")
            part2.write_text("part2", encoding="utf-8")
            task = create_local_upload_task(str(local_file), notebook_id="nb123", notebook_title=None, workspace_root=root)

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, _file_path, _file_format=None):
                    return [part1, part2]

                def upload_to_notebooklm(self, file_path, notebook_id=None):
                    if file_path != [part1, part2]:
                        raise AssertionError("unexpected upload file list")
                    return {"success": True, "source_ids": ["src1", "src2"], "notebook_id": notebook_id, "title": "Book", "chunks": 2}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_local_upload_task(task)

            manifest = json.loads(task_manifest_path(task.id, root).read_text(encoding="utf-8"))

        self.assertEqual(task.status, "completed")
        self.assertEqual([part["status"] for part in task.parts], ["uploaded", "uploaded"])
        self.assertEqual([part["source_id"] for part in task.parts], ["src1", "src2"])
        self.assertEqual(manifest["parts"][1]["filename"], part2.name)
        self.assertEqual(manifest["uploads"][0]["source_ids"], ["src1", "src2"])

    def test_run_local_upload_task_records_failed_parts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part1 = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_002.md"
            part2 = root / "task-1" / "books" / "book" / "parts" / "book_part_002_of_002.md"
            local_file.parent.mkdir(parents=True)
            part1.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part1.write_text("part1", encoding="utf-8")
            part2.write_text("part2", encoding="utf-8")
            task = create_local_upload_task(str(local_file), notebook_id="nb123", notebook_title=None, workspace_root=root)

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, _file_path, _file_format=None):
                    return [part1, part2]

                def upload_to_notebooklm(self, _file_path, notebook_id=None):
                    return {
                        "success": False,
                        "notebook_id": notebook_id,
                        "source_ids": ["src1"],
                        "failed_chunks": [{"file": str(part2), "error": "timeout"}],
                        "chunks": 2,
                        "error": "分块上传失败: 1/2 个分块失败",
                    }

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_local_upload_task(task)

            manifest = json.loads(task_manifest_path(task.id, root).read_text(encoding="utf-8"))

        self.assertEqual(task.status, "failed")
        self.assertEqual(task.parts[0]["status"], "uploaded")
        self.assertEqual(task.parts[1]["status"], "failed")
        self.assertEqual(task.parts[1]["error"], "timeout")
        self.assertEqual(manifest["uploads"][0]["status"], "failed")

    def test_run_local_upload_task_uses_existing_sources_without_reconverting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part1 = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_002.md"
            part2 = root / "task-1" / "books" / "book" / "parts" / "book_part_002_of_002.md"
            local_file.parent.mkdir(parents=True)
            part1.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part1.write_text("part1", encoding="utf-8")
            part2.write_text("part2", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "mode": "download",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(part1),
                "file_format": "md",
                "status": "completed",
                "stage": "processed",
                "parts": [
                    {"index": 1, "path": str(part1), "filename": part1.name, "status": "ready", "source_id": None, "error": None},
                    {"index": 2, "path": str(part2), "filename": part2.name, "status": "ready", "source_id": None, "error": None},
                ],
                "uploads": [],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            task = create_local_upload_task(str(local_file), notebook_id="nb123", notebook_title=None, workspace_root=root, task_id="task-1")
            upload_paths = []

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, *_args, **_kwargs):
                    raise AssertionError("existing upload sources must not be regenerated during upload")

                def upload_to_notebooklm(self, file_path, notebook_id=None):
                    upload_paths.append(file_path)
                    return {"success": True, "source_ids": ["src1", "src2"], "notebook_id": notebook_id, "title": "Book", "chunks": 2}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_local_upload_task(task)

            saved = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.status, "completed")
        self.assertEqual(upload_paths, [[part1.resolve(), part2.resolve()]])
        self.assertEqual([part["source_id"] for part in saved["parts"]], ["src1", "src2"])
        self.assertEqual(saved["uploads"][0]["scope"], "source_batch")
        self.assertEqual(len(saved["uploads"][0]["source_records"]), 2)

    def test_run_sources_upload_task_uploads_selected_parts_and_records_per_source_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part1 = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_003.md"
            part2 = root / "task-1" / "books" / "book" / "parts" / "book_part_002_of_003.md"
            part3 = root / "task-1" / "books" / "book" / "parts" / "book_part_003_of_003.md"
            local_file.parent.mkdir(parents=True)
            part1.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            for part in (part1, part2, part3):
                part.write_text(part.name, encoding="utf-8")
            manifest = {
                "id": "task-1",
                "mode": "download",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(part1),
                "file_format": "md",
                "status": "completed",
                "stage": "processed",
                "parts": [
                    {"index": 1, "path": str(part1), "filename": part1.name, "status": "ready", "source_id": None, "error": None},
                    {"index": 2, "path": str(part2), "filename": part2.name, "status": "failed", "source_id": None, "error": "old timeout"},
                    {"index": 3, "path": str(part3), "filename": part3.name, "status": "uploaded", "source_id": "old-src3", "error": None},
                ],
                "uploads": [],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            upload_paths = []
            task = create_sources_upload_task(
                [str(part1), str(part2)],
                notebook_id="nb-new",
                notebook_title="New Notes",
                workspace_root=root,
                task_id="task-1",
            )

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def upload_to_notebooklm(self, file_path, notebook_id=None):
                    upload_paths.append(file_path)
                    return {"success": True, "source_ids": ["src1", "src2"], "notebook_id": notebook_id, "title": "Selected", "chunks": 2}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_sources_upload_task(task)

            saved = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))
            assets = scan_local_assets(root)

        self.assertEqual(task.status, "completed")
        self.assertEqual(upload_paths, [[part1.resolve(), part2.resolve()]])
        self.assertEqual([part["status"] for part in saved["parts"]], ["uploaded", "uploaded", "uploaded"])
        self.assertEqual([part["source_id"] for part in saved["parts"]], ["src1", "src2", "old-src3"])
        self.assertEqual(saved["uploads"][0]["scope"], "source_batch")
        self.assertEqual(saved["uploads"][0]["notebook_title"], "New Notes")
        self.assertEqual(saved["uploads"][0]["source_records"][1]["source_path"], str(part2.resolve()))
        source_two = assets[0]["upload_sources"][1]
        self.assertEqual(source_two["upload_records"][0]["source_id"], "src2")
        self.assertEqual(source_two["last_notebook_title"], "New Notes")

    def test_process_local_task_keep_strategy_preserves_existing_parts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_001.md"
            local_file.parent.mkdir(parents=True)
            part.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part.write_text("part", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "mode": "download",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(part),
                "file_format": "md",
                "status": "completed",
                "stage": "processed",
                "parts": [{"index": 1, "path": str(part), "filename": part.name, "status": "uploaded", "source_id": "src1", "error": None}],
                "uploads": [],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            task = create_process_local_task(str(local_file), workspace_root=root, task_id="task-1", strategy="keep")

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, *_args, **_kwargs):
                    raise AssertionError("keep strategy must not regenerate existing parts")

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_process_local_task(task)

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.stage, "processed")
        self.assertEqual(task.parts[0]["source_id"], "src1")

    def test_process_local_task_requires_explicit_strategy_when_parts_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_001.md"
            local_file.parent.mkdir(parents=True)
            part.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part.write_text("part", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(part),
                "file_format": "md",
                "parts": [{"index": 1, "path": str(part), "filename": part.name, "status": "ready"}],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(BadRequest, "已经处理"):
                create_process_local_task(str(local_file), workspace_root=root, task_id="task-1")

    def test_process_local_task_version_strategy_uses_versioned_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            old_part = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_001.md"
            local_file.parent.mkdir(parents=True)
            old_part.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            old_part.write_text("old", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(old_part),
                "file_format": "md",
                "parts": [{"index": 1, "path": str(old_part), "filename": old_part.name, "status": "uploaded", "source_id": "old-src"}],
                "uploads": [],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            task = create_process_local_task(str(local_file), workspace_root=root, task_id="task-1", strategy="version")
            converted_inputs = []

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, file_path, _file_format=None):
                    converted_inputs.append(file_path)
                    new_part = root / "task-1" / "books" / file_path.stem / "parts" / f"{file_path.stem}_part_001_of_001.md"
                    new_part.parent.mkdir(parents=True)
                    new_part.write_text("new", encoding="utf-8")
                    return [new_part]

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_process_local_task(task)

        self.assertEqual(task.status, "completed")
        self.assertEqual(converted_inputs[0].name, "book_v002.md")
        self.assertIn("book_v002", task.parts[0]["path"])
        self.assertEqual(task.parts[0]["status"], "ready")

    def test_run_source_upload_task_uploads_one_part_and_updates_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part1 = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_002.md"
            part2 = root / "task-1" / "books" / "book" / "parts" / "book_part_002_of_002.md"
            local_file.parent.mkdir(parents=True)
            part1.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part1.write_text("part1", encoding="utf-8")
            part2.write_text("part2", encoding="utf-8")
            manifest = {
                "id": "task-1",
                "mode": "download",
                "local_path": str(local_file),
                "downloaded_file": str(local_file),
                "final_file": str(part1),
                "file_format": "md",
                "status": "completed",
                "stage": "processed",
                "parts": [
                    {"index": 1, "path": str(part1), "filename": part1.name, "status": "ready", "source_id": None, "error": None},
                    {"index": 2, "path": str(part2), "filename": part2.name, "status": "ready", "source_id": None, "error": None},
                ],
                "uploads": [],
            }
            (root / "task-1").mkdir(exist_ok=True)
            (root / "task-1" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            task = create_source_upload_task(str(part2), notebook_id="nb123", notebook_title=None, workspace_root=root, task_id="task-1")

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def upload_to_notebooklm(self, file_path, notebook_id=None):
                    return {"success": True, "source_id": "src2", "notebook_id": notebook_id, "title": Path(file_path).stem}

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_source_upload_task(task)

            saved = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.status, "completed")
        self.assertEqual(saved["parts"][0]["status"], "ready")
        self.assertEqual(saved["parts"][1]["status"], "uploaded")
        self.assertEqual(saved["parts"][1]["source_id"], "src2")
        self.assertEqual(saved["uploads"][0]["scope"], "single_source")

    def test_run_process_local_task_records_processed_parts_without_uploading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_001.md"
            local_file.parent.mkdir(parents=True)
            part.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part.write_text("part", encoding="utf-8")
            task = create_process_local_task(str(local_file), workspace_root=root)

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, _file_path, _file_format=None):
                    return [part]

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_process_local_task(task)

        self.assertEqual(task.status, "completed")
        self.assertEqual(task.stage, "processed")
        self.assertEqual(task.parts[0]["status"], "ready")

    def test_process_local_task_can_update_existing_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_file = root / "task-1" / "downloads" / "book.md"
            part = root / "task-1" / "books" / "book" / "parts" / "book_part_001_of_001.md"
            local_file.parent.mkdir(parents=True)
            part.parent.mkdir(parents=True)
            local_file.write_text("source", encoding="utf-8")
            part.write_text("part", encoding="utf-8")
            original = create_download_task("https://zh.zlib.li/book/example", workspace_root=root)
            original.id = "task-1"
            original.downloaded_file = str(local_file)
            original.final_file = str(local_file)
            original.file_format = "md"
            save_task_manifest(original)
            task = create_process_local_task(str(local_file), workspace_root=root, task_id="task-1")

            class FakeUploader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def convert_to_txt(self, _file_path, _file_format=None):
                    return [part]

            with patch("scripts.web_api.ZLibraryAutoUploader", FakeUploader):
                run_process_local_task(task)

            manifest = json.loads((root / "task-1" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(task.id, "task-1")
        self.assertEqual(manifest["id"], "task-1")
        self.assertEqual(manifest["parts"][0]["filename"], part.name)

    def test_resolve_static_file_rejects_sibling_path_prefix_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "dist"
            sibling = root / "dist_evil"
            base.mkdir()
            sibling.mkdir()
            (base / "index.html").write_text("index", encoding="utf-8")
            (sibling / "secret.txt").write_text("secret", encoding="utf-8")

            resolved = resolve_static_file("/../dist_evil/secret.txt", base)

        self.assertEqual(resolved.name, "index.html")

    def test_read_json_body_reports_invalid_json_as_bad_request(self):
        handler = type(
            "Handler",
            (),
            {
                "headers": {"Content-Length": "1"},
                "rfile": BytesIO(b"{"),
            },
        )()

        with self.assertRaises(BadRequest):
            read_json_body(handler)

    def test_resolve_notebooklm_command_checks_python_bin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = Path(temp_dir) / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python3"
            notebooklm = bin_dir / "notebooklm"
            python.write_text("", encoding="utf-8")
            notebooklm.write_text("", encoding="utf-8")

            with patch("scripts.web_api.shutil.which", return_value=None):
                with patch("scripts.web_api.sys.executable", str(python)):
                    command = resolve_notebooklm_command()

        self.assertEqual(command, str(notebooklm))

    def test_run_notebooklm_reports_unresolved_cli_clearly(self):
        with patch("scripts.web_api.resolve_notebooklm_command", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "notebooklm"):
                run_notebooklm(["list", "--json"])

    def test_run_notebooklm_uses_resolved_command(self):
        completed = subprocess.CompletedProcess(["notebooklm"], 0, stdout="[]", stderr="")
        with patch("scripts.web_api.resolve_notebooklm_command", return_value="/tmp/notebooklm"):
            with patch("subprocess.run", return_value=completed) as run:
                result = run_notebooklm(["list", "--json"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_args.args[0], ["/tmp/notebooklm", "list", "--json"])

    def test_run_notebooklm_reports_subprocess_missing_cli_clearly(self):
        with patch("scripts.web_api.resolve_notebooklm_command", return_value="notebooklm"):
            with patch("subprocess.run", side_effect=FileNotFoundError("notebooklm")):
                with self.assertRaisesRegex(RuntimeError, "notebooklm"):
                    run_notebooklm(["list", "--json"])

    def test_run_notebooklm_reports_timeout_clearly(self):
        with patch("scripts.web_api.resolve_notebooklm_command", return_value="notebooklm"):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["notebooklm"], 8)):
                with self.assertRaisesRegex(RuntimeError, "超时"):
                    run_notebooklm(["list", "--json"], timeout=8)

    def test_zlibrary_auth_status_reports_saved_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zlibrary_dir = root / ".zlibrary"
            zlibrary_dir.mkdir()
            (zlibrary_dir / "storage_state.json").write_text("{}", encoding="utf-8")

            with patch("scripts.web_api.Path.home", return_value=root):
                status = get_zlibrary_auth_status()

        self.assertTrue(status["logged_in"])
        self.assertEqual(status["status"], "saved")

    def test_notebooklm_auth_status_reports_missing_cli(self):
        with patch("scripts.web_api.resolve_notebooklm_command", return_value=None):
            status = get_notebooklm_auth_status()

        self.assertFalse(status["installed"])
        self.assertFalse(status["logged_in"])
        self.assertEqual(status["status"], "missing")

    def test_get_auth_status_can_skip_notebooklm_probe(self):
        with patch("scripts.web_api.NOTEBOOKLM_STATUS_CACHE", None):
            with patch("scripts.web_api.get_zlibrary_auth_status", return_value={"status": "saved"}):
                with patch("scripts.web_api.resolve_notebooklm_command", return_value="/tmp/notebooklm"):
                    with patch("scripts.web_api.run_notebooklm", side_effect=AssertionError("should not probe")):
                        status = get_auth_status(probe_notebooklm=False)

        self.assertEqual(status["zlibrary"]["status"], "saved")
        self.assertEqual(status["notebooklm"]["status"], "unchecked")

    def test_get_auth_status_uses_cached_notebooklm_status_when_probe_is_skipped(self):
        cached = {
            "installed": True,
            "logged_in": True,
            "status": "ready",
            "message": "NotebookLM CLI 已登录",
            "login_process": None,
        }
        with patch("scripts.web_api.NOTEBOOKLM_STATUS_CACHE", cached):
            with patch("scripts.web_api.get_zlibrary_auth_status", return_value={"status": "saved"}):
                status = get_auth_status(probe_notebooklm=False)

        self.assertTrue(status["notebooklm"]["logged_in"])
        self.assertEqual(status["notebooklm"]["status"], "ready")

    def test_start_notebooklm_login_reports_missing_cli(self):
        with patch("scripts.web_api.resolve_notebooklm_command", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "NotebookLM CLI"):
                start_notebooklm_login()

    def test_start_notebooklm_login_prefers_system_chrome(self):
        class RunningProcess:
            def poll(self):
                return None

        with patch("scripts.web_api.NOTEBOOKLM_LOGIN_PROCESS", None):
            with patch("scripts.web_api.resolve_notebooklm_command", return_value="/tmp/notebooklm"):
                with patch("scripts.web_api.choose_system_browser_channel", return_value=("chrome", "系统 Chrome")):
                    with patch("subprocess.Popen", return_value=RunningProcess()) as popen:
                        start_notebooklm_login()

        self.assertEqual(popen.call_args.args[0], ["/tmp/notebooklm", "login", "--browser", "chrome"])

    def test_cancel_notebooklm_login_terminates_running_process(self):
        class RunningProcess:
            def __init__(self):
                self.terminated = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

        process = RunningProcess()
        with patch("scripts.web_api.NOTEBOOKLM_LOGIN_PROCESS", process):
            with patch("scripts.web_api.resolve_notebooklm_command", return_value="/tmp/notebooklm"):
                status = cancel_notebooklm_login()

        self.assertTrue(process.terminated)
        self.assertEqual(status["status"], "not_logged_in")
        self.assertEqual(status["message"], "NotebookLM 登录流程已取消")

    def test_format_zlibrary_login_error_explains_missing_chromium(self):
        message = format_zlibrary_login_error(
            RuntimeError("BrowserType.launch_persistent_context: Executable doesn't exist")
        )

        self.assertIn("没有找到可用浏览器", message)
        self.assertIn("playwright install chromium", message)

    def test_choose_chromium_launch_options_uses_bundled_browser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "chromium"
            executable.write_text("", encoding="utf-8")
            chromium = type("Chromium", (), {"executable_path": str(executable)})()

            choice = choose_chromium_launch_options(chromium)

        self.assertEqual(choice.options, {})
        self.assertIsNone(choice.log)

    def test_choose_chromium_launch_options_falls_back_to_system_chrome(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-chromium"
            system_chrome = Path(temp_dir) / "Google Chrome"
            system_chrome.write_text("", encoding="utf-8")
            chromium = type("Chromium", (), {"executable_path": str(missing)})()

            with patch("scripts.browser.SYSTEM_BROWSER_CHANNELS", (("chrome", system_chrome, "系统 Chrome"),)):
                choice = choose_chromium_launch_options(chromium)

        self.assertEqual(choice.options, {"channel": "chrome"})
        self.assertIn("系统 Chrome", choice.log or "")

    def test_choose_chromium_launch_options_reports_missing_browser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-chromium"
            chromium = type("Chromium", (), {"executable_path": str(missing)})()

            with patch("scripts.browser.SYSTEM_BROWSER_CHANNELS", ()):
                with self.assertRaisesRegex(RuntimeError, "playwright install chromium"):
                    choose_chromium_launch_options(chromium)


if __name__ == "__main__":
    unittest.main()
