import json
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from scripts.web_api import (
    BadRequest,
    cancel_notebooklm_login,
    choose_chromium_launch_options,
    create_task,
    format_zlibrary_login_error,
    get_auth_status,
    get_notebooklm_auth_status,
    get_zlibrary_auth_status,
    parse_created_notebook,
    parse_notebooks,
    read_json_body,
    resolve_notebooklm_command,
    resolve_static_file,
    run_notebooklm,
    serialize_task,
    start_notebooklm_login,
)


class WebApiTest(unittest.TestCase):
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
