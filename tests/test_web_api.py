import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from scripts.web_api import (
    BadRequest,
    create_task,
    parse_created_notebook,
    parse_notebooks,
    read_json_body,
    resolve_static_file,
    run_notebooklm,
    serialize_task,
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

    def test_run_notebooklm_reports_missing_cli_clearly(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("notebooklm")):
            with self.assertRaisesRegex(RuntimeError, "notebooklm"):
                run_notebooklm(["list", "--json"])


if __name__ == "__main__":
    unittest.main()
