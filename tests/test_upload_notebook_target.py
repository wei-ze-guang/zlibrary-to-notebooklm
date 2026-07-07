import contextlib
import io
import unittest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.upload import ZLibraryAutoUploader


class UploadNotebookTargetTest(unittest.TestCase):
    def test_single_file_upload_uses_existing_notebook_id_without_shell(self):
        uploader = ZLibraryAutoUploader()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            stdout = '{"source": {"id": "src123"}}'
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

        with patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stdout(io.StringIO()):
                result = uploader.upload_to_notebooklm(Path("/tmp/book's notes.pdf"), notebook_id="nb123")

        self.assertTrue(result["success"])
        self.assertEqual(result["notebook_id"], "nb123")
        self.assertEqual(
            calls,
            [
                (
                    ["notebooklm", "source", "add", "/tmp/book's notes.pdf", "--notebook", "nb123", "--json"],
                    {"capture_output": True, "text": True, "check": False},
                )
            ],
        )

    def test_create_notebook_uses_argument_list_for_titles_with_quotes(self):
        uploader = ZLibraryAutoUploader()
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            if args[:2] == ["notebooklm", "create"]:
                stdout = '{"notebook": {"id": "nb123"}}'
            else:
                stdout = '{"source": {"id": "src123"}}'
            return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

        with patch("subprocess.run", side_effect=fake_run):
            with contextlib.redirect_stdout(io.StringIO()):
                result = uploader.upload_to_notebooklm(Path("/tmp/book.pdf"), title="Alice's Book")

        self.assertTrue(result["success"])
        self.assertEqual(calls[0][0], ["notebooklm", "create", "Alice's Book", "--json"])
        self.assertNotIn("shell", calls[0][1])

    def test_epub_conversion_uses_argument_list_for_paths_with_quotes(self):
        uploader = ZLibraryAutoUploader()
        calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            uploader.temp_dir = Path(temp_dir)
            epub_file = Path(temp_dir) / "book's copy.epub"
            epub_file.write_text("fake epub", encoding="utf-8")

            def fake_run(args, **kwargs):
                calls.append((args, kwargs))
                Path(args[3]).write_text("short markdown", encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("subprocess.run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = uploader.convert_to_txt(epub_file, "epub")

        self.assertEqual(result.name, "book's copy.md")
        self.assertEqual(calls[0][0][0], sys.executable)
        self.assertEqual(calls[0][1], {"capture_output": True, "text": True, "check": False})


if __name__ == "__main__":
    unittest.main()
