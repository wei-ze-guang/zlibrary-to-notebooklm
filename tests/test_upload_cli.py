import contextlib
import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from scripts.upload import ZLibraryAutoUploader, parse_args


class UploadCliTest(unittest.TestCase):
    def test_parse_args_accepts_zlibrary_url(self):
        args = parse_args(["https://zh.zlib.li/book/12345/example"])

        self.assertEqual(args.url, "https://zh.zlib.li/book/12345/example")

    def test_parse_args_handles_help_before_browser_starts(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc_info:
                parse_args(["--help"])

        self.assertEqual(exc_info.exception.code, 0)
        self.assertIn("Z-Library URL", output.getvalue())

    def test_download_returns_tuple_when_session_is_missing(self):
        uploader = ZLibraryAutoUploader()

        with tempfile.TemporaryDirectory() as temp_dir:
            uploader.config_dir = Path(temp_dir)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                result = asyncio.run(uploader.download_from_zlibrary("https://zh.zlib.li/book/example"))

        self.assertEqual(result, (None, None))
        self.assertIn("python3 scripts/login.py", output.getvalue())


if __name__ == "__main__":
    unittest.main()
