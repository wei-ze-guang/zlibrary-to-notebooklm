import contextlib
import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_download_returns_tuple_when_clicking_download_link_fails(self):
        class FakeLink:
            async def get_attribute(self, _name):
                return "/dl/book.pdf"

            async def evaluate(self, _script):
                raise RuntimeError("click failed")

        class FakePage:
            def set_default_timeout(self, _timeout):
                return None

            def on(self, _event, _handler):
                return None

            async def goto(self, *_args, **_kwargs):
                return None

            async def query_selector(self, _selector):
                return None

            async def query_selector_all(self, selector):
                if selector == 'a[href*="/dl/"]':
                    return [FakeLink()]
                return []

        class FakeBrowser:
            def __init__(self):
                self.pages = [FakePage()]

            async def close(self):
                return None

        class FakeChromium:
            async def launch_persistent_context(self, *_args, **_kwargs):
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakePlaywrightContext:
            async def __aenter__(self):
                return FakePlaywright()

            async def __aexit__(self, *_args):
                return None

        async def fast_sleep(_seconds):
            return None

        uploader = ZLibraryAutoUploader()

        with tempfile.TemporaryDirectory() as temp_dir:
            uploader.config_dir = Path(temp_dir)
            (Path(temp_dir) / "storage_state.json").write_text("{}", encoding="utf-8")
            with patch("scripts.upload.get_async_playwright", return_value=lambda: FakePlaywrightContext()):
                with patch("scripts.upload.choose_chromium_launch_options", return_value=type("Choice", (), {"log": None, "options": {}})()):
                    with patch("scripts.upload.asyncio.sleep", new=fast_sleep):
                        with contextlib.redirect_stdout(io.StringIO()):
                            result = asyncio.run(uploader.download_from_zlibrary("https://zh.zlib.li/book/example"))

        self.assertEqual(result, (None, None))


if __name__ == "__main__":
    unittest.main()
