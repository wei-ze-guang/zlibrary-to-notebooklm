import contextlib
import io
import unittest

from scripts.login import parse_args


class LoginCliTest(unittest.TestCase):
    def test_parse_args_handles_help_before_browser_starts(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc_info:
                parse_args(["--help"])

        self.assertEqual(exc_info.exception.code, 0)
        self.assertIn("Z-Library 登录", output.getvalue())


if __name__ == "__main__":
    unittest.main()
