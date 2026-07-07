#!/usr/bin/env python3
"""
Z-Library 搜索结果展示工具
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin

try:
    from scripts.browser import choose_chromium_launch_options
except ImportError:
    from browser import choose_chromium_launch_options


DEFAULT_BASE_URL = "https://zh.zlib.li"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    details: str = ""


class HtmlNode:
    def __init__(self, name: str, attrs: dict[str, str], parent: "HtmlNode | None" = None):
        self.name = name
        self.attrs = attrs
        self.parent = parent
        self.children: list[HtmlNode] = []
        self.text_parts: list[str] = []

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.attrs.get(key, default)

    def get_text(self, separator: str = "") -> str:
        parts = [*self.text_parts]
        parts.extend(child.get_text(separator) for child in self.children)
        return separator.join(part for part in parts if part)

    def find(self, names: list[str] | tuple[str, ...] | str):
        accepted = {names} if isinstance(names, str) else set(names)
        for child in self.children:
            if child.name in accepted:
                return child
            found = child.find(names)
            if found:
                return found
        return None

    def find_parent(self, class_=None):
        node = self.parent
        while node:
            class_value = node.get("class", "") or ""
            if class_ is None or class_.search(class_value):
                return node
            node = node.parent
        return None

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()


class SearchHtmlParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].name == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.stack[-1].text_parts.append(data)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments before starting browser automation."""
    parser = argparse.ArgumentParser(
        prog="search.py",
        description="在 Z-Library 中搜索书籍并展示结果链接",
    )
    parser.add_argument("query", metavar="搜索关键词", help="书名、作者或关键词")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="最多展示多少条结果，默认 10",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Z-Library 站点地址，默认 {DEFAULT_BASE_URL}",
    )
    return parser.parse_args(argv)


def get_async_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        print("❌ Playwright 未安装")
        print("请运行: pip install -r requirements.txt")
        sys.exit(1)


def build_search_url(query: str, base_url: str = DEFAULT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/s/{quote(query.strip())}"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_book_link(href: str | None) -> bool:
    return bool(href and re.search(r"/book/[^/?#]+", href))


def is_networkidle_timeout(error: Exception) -> bool:
    message = str(error).lower()
    return "timeout" in message


def _extract_title(link) -> str:
    title_attr = link.get("title")
    if title_attr:
        return _clean_text(title_attr)

    heading = link.find(["h1", "h2", "h3", "h4"])
    if heading:
        return _clean_text(heading.get_text(" "))
    return _clean_text(link.get_text(" "))


def _extract_details(card, title: str) -> str:
    text = _clean_text(card.get_text(" "))
    if title and text.startswith(title):
        text = _clean_text(text[len(title):])
    return text


def _extract_bookcard_details(bookcard) -> str:
    values = []
    for attr in ("author", "publisher", "year", "extension", "filesize", "language"):
        value = bookcard.get(attr)
        if value:
            values.append(_clean_text(value))
    return ", ".join(values)


def extract_search_results(html: str, base_url: str = DEFAULT_BASE_URL, limit: int = 10) -> list[SearchResult]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        candidates = soup.find_all(["a", "z-bookcard"], href=True)
    except ImportError:
        parser = SearchHtmlParser()
        parser.feed(html)
        candidates = [node for node in parser.root.walk() if node.name in ("a", "z-bookcard") and node.get("href")]

    results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for link in candidates:
        href = link.get("href")
        if not _looks_like_book_link(href):
            continue

        url = urljoin(base_url.rstrip("/") + "/", href)
        if url in seen_urls:
            continue

        title = _extract_title(link)
        if not title:
            continue

        card = link.find_parent(class_=re.compile(r"(book|item|card|res|result)", re.I))
        if link.name == "z-bookcard":
            details = _extract_bookcard_details(link)
        else:
            details = _extract_details(card, title) if card else ""

        results.append(SearchResult(title=title, url=url, details=details))
        seen_urls.add(url)

        if len(results) >= limit:
            break

    return results


def format_results(results: list[SearchResult]) -> str:
    if not results:
        return "未找到搜索结果。"

    lines: list[str] = []
    for index, result in enumerate(results, 1):
        lines.append(f"{index}. {result.title}")
        if result.details:
            lines.append(f"   信息: {result.details}")
        lines.append(f"   链接: {result.url}")
        lines.append("")
    return "\n".join(lines).rstrip()


async def search_zlibrary(query: str, limit: int = 10, base_url: str = DEFAULT_BASE_URL) -> list[SearchResult]:
    config_dir = Path.home() / ".zlibrary"
    storage_state = config_dir / "storage_state.json"

    if not storage_state.exists():
        print("❌ 未找到 Z-Library 会话状态")
        print("💡 请先运行: python3 scripts/login.py")
        return []

    search_url = build_search_url(query, base_url)
    print("=" * 70)
    print("🔍 Z-Library 搜索")
    print("=" * 70)
    print(f"关键词: {query}")
    print(f"地址: {search_url}")

    async with get_async_playwright()() as p:
        launch_choice = choose_chromium_launch_options(p.chromium)
        if launch_choice.log:
            print(f"ℹ️  {launch_choice.log}")
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(config_dir / "browser_profile"),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            **launch_choice.options,
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        page.set_default_timeout(60000)

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as exc:
                if not is_networkidle_timeout(exc):
                    raise
                print("⚠️  页面仍有网络请求，继续解析已加载内容...")
            html = await page.content()
            return extract_search_results(html, base_url, limit)
        finally:
            await browser.close()


async def main():
    args = parse_args()
    results = await search_zlibrary(args.query, args.limit, args.base_url)
    print("")
    print(format_results(results))


if __name__ == "__main__":
    asyncio.run(main())
