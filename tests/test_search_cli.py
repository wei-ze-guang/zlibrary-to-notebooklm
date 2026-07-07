import contextlib
import io
import unittest

from scripts.search import build_search_url, extract_search_results, format_results, is_networkidle_timeout, parse_args


class SearchCliTest(unittest.TestCase):
    def test_parse_args_accepts_query_and_limit(self):
        args = parse_args(["机器学习", "--limit", "5"])

        self.assertEqual(args.query, "机器学习")
        self.assertEqual(args.limit, 5)

    def test_parse_args_handles_help_before_browser_starts(self):
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exc_info:
                parse_args(["--help"])

        self.assertEqual(exc_info.exception.code, 0)
        self.assertIn("搜索关键词", output.getvalue())

    def test_build_search_url_quotes_query(self):
        url = build_search_url("machine learning", "https://zh.zlib.li")

        self.assertEqual(url, "https://zh.zlib.li/s/machine%20learning")

    def test_is_networkidle_timeout_detects_playwright_timeout_message(self):
        error = TimeoutError("Timeout 15000ms exceeded")

        self.assertTrue(is_networkidle_timeout(error))

    def test_extract_search_results_from_z_bookcards(self):
        html = """
        <div class="book-item resItemBoxBooks">
            <div class="counter">1</div>
            <z-bookcard
                href="/book/zZ2DYk5egE/%E6%93%8D%E4%BD%9C%E7%B3%BB%E7%BB%9F.html"
                title="操作系统概念 原书第9版"
                author="Abraham Silberschatz"
                publisher="机械工业出版社"
                extension="PDF"
                year="2018"
                filesize="166.63 MB">
            </z-bookcard>
        </div>
        """

        results = extract_search_results(html, "https://zh.zlib.li", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "操作系统概念 原书第9版")
        self.assertEqual(
            results[0].url,
            "https://zh.zlib.li/book/zZ2DYk5egE/%E6%93%8D%E4%BD%9C%E7%B3%BB%E7%BB%9F.html",
        )
        self.assertIn("Abraham Silberschatz", results[0].details)
        self.assertIn("PDF", results[0].details)

    def test_extract_search_results_from_book_cards(self):
        html = """
        <div class="book-item">
            <a href="/book/123/example-book">
                <h3>Example Book</h3>
            </a>
            <div class="authors">Alice Chen</div>
            <div class="property_value">PDF, 2019, 12 MB</div>
        </div>
        <div class="book-item">
            <a href="https://zh.zlib.li/book/456/another-book">Another Book</a>
            <div>Bob Li</div>
            <div>EPUB, 2021, 4 MB</div>
        </div>
        """

        results = extract_search_results(html, "https://zh.zlib.li", limit=10)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "Example Book")
        self.assertEqual(results[0].url, "https://zh.zlib.li/book/123/example-book")
        self.assertIn("Alice Chen", results[0].details)
        self.assertEqual(results[1].title, "Another Book")
        self.assertEqual(results[1].url, "https://zh.zlib.li/book/456/another-book")

    def test_format_results_prints_numbered_links(self):
        html = """
        <div class="book-item">
            <a href="/book/123/example-book"><h3>Example Book</h3></a>
            <div>PDF, 2019</div>
        </div>
        """
        results = extract_search_results(html, "https://zh.zlib.li", limit=10)

        output = format_results(results)

        self.assertIn("1. Example Book", output)
        self.assertIn("链接: https://zh.zlib.li/book/123/example-book", output)


if __name__ == "__main__":
    unittest.main()
