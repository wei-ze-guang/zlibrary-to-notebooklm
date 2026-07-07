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
        uploader = ZLibraryAutoUploader(task_id="task-1")
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
                    [
                        "notebooklm",
                        "source",
                        "add",
                        "/tmp/book's notes.pdf",
                        "--notebook",
                        "nb123",
                        "--title",
                        "book's notes",
                        "--timeout",
                        "180",
                        "--json",
                    ],
                    {"capture_output": True, "text": True, "check": False},
                )
            ],
        )

    def test_create_notebook_uses_argument_list_for_titles_with_quotes(self):
        uploader = ZLibraryAutoUploader(task_id="task-1")
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
        uploader = ZLibraryAutoUploader(task_id="task-1")
        calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            uploader.workspace_root = Path(temp_dir)
            epub_file = Path(temp_dir) / "book's copy.epub"
            epub_file.write_text("fake epub", encoding="utf-8")

            def fake_run(args, **kwargs):
                calls.append((args, kwargs))
                Path(args[3]).write_text("short markdown", encoding="utf-8")
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("subprocess.run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = uploader.convert_to_txt(epub_file, "epub")

        self.assertEqual(result.name, "books-copy.md")
        self.assertIn("books-copy", str(result.parent))
        self.assertEqual(calls[0][0][0], sys.executable)
        self.assertEqual(calls[0][1], {"capture_output": True, "text": True, "check": False})

    def test_split_markdown_file_uses_task_scoped_zero_padded_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploader = ZLibraryAutoUploader(
                task_id="task/42",
                workspace_root=Path(temp_dir),
                chunk_max_words=4,
            )
            markdown = Path(temp_dir) / "Strange Book 2024!.md"
            markdown.write_text(
                "# Strange Book\n\nalpha beta\n\n"
                "## Chapter One\n\none two\n\n"
                "## Chapter Two\n\nthree four\n\n"
                "## Chapter Three\n\nfive six\n",
                encoding="utf-8",
            )

            chunks = uploader.split_markdown_file(markdown, max_words=4)

        self.assertEqual(
            [chunk.name for chunk in chunks],
            [
                "strange-book-2024_part_001_of_004.md",
                "strange-book-2024_part_002_of_004.md",
                "strange-book-2024_part_003_of_004.md",
                "strange-book-2024_part_004_of_004.md",
            ],
        )
        self.assertIn("task-42/books/strange-book-2024/parts", str(chunks[0].parent))

    def test_convert_to_txt_splits_large_markdown_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploader = ZLibraryAutoUploader(
                task_id="task-1",
                workspace_root=Path(temp_dir),
                chunk_max_words=3,
            )
            markdown = Path(temp_dir) / "Long Notes.md"
            markdown.write_text("# One\n\nalpha\n\n## Two\n\nbeta", encoding="utf-8")

            result = uploader.convert_to_txt(markdown)

        self.assertIsInstance(result, list)
        self.assertEqual([path.name for path in result], ["long-notes_part_001_of_002.md", "long-notes_part_002_of_002.md"])

    def test_split_markdown_file_breaks_oversized_paragraphs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploader = ZLibraryAutoUploader(
                task_id="task-1",
                workspace_root=Path(temp_dir),
                chunk_max_words=3,
            )
            markdown = Path(temp_dir) / "Dense Notes.md"
            markdown.write_text("one two three four five six seven", encoding="utf-8")

            chunks = uploader.split_markdown_file(markdown, max_words=3)
            chunk_word_counts = [uploader.count_words(chunk.read_text(encoding="utf-8")) for chunk in chunks]

        self.assertEqual(
            [chunk.name for chunk in chunks],
            [
                "dense-notes_part_001_of_003.md",
                "dense-notes_part_002_of_003.md",
                "dense-notes_part_003_of_003.md",
            ],
        )
        self.assertLessEqual(max(chunk_word_counts), 3)

    def test_chunk_upload_uses_titles_and_fails_when_any_chunk_fails(self):
        uploader = ZLibraryAutoUploader(task_id="task-1")
        calls = []

        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "book_part_001_of_002.md"
            second = Path(temp_dir) / "book_part_002_of_002.md"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")

            def fake_run(args, **kwargs):
                calls.append((args, kwargs))
                if str(second) in args:
                    return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "upload failed"})()
                return type("Result", (), {"returncode": 0, "stdout": '{"source": {"id": "src1"}}', "stderr": ""})()

            with patch("subprocess.run", side_effect=fake_run):
                with contextlib.redirect_stdout(io.StringIO()):
                    result = uploader.upload_to_notebooklm([first, second], notebook_id="nb123", title="Book")

        self.assertFalse(result["success"])
        self.assertIn("分块上传失败", result["error"])
        self.assertIn("--title", calls[0][0])
        self.assertIn("Book - Part 001/002", calls[0][0])


if __name__ == "__main__":
    unittest.main()
