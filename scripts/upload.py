#!/usr/bin/env python3
"""
Z-Library 全自动下载并上传到 NotebookLM
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import shutil
import sys
import tempfile
import time
import re
import uuid
from pathlib import Path

try:
    from scripts.browser import choose_chromium_launch_options
except ImportError:
    from browser import choose_chromium_launch_options


DEFAULT_CHUNK_MAX_WORDS = 350000
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 180
DEFAULT_DOWNLOAD_EVENT_TIMEOUT_MS = 60000
LARGE_DIRECT_UPLOAD_WARNING_BYTES = 200 * 1024 * 1024
TEXT_SOURCE_EXTENSIONS = {".md", ".markdown", ".txt"}


def safe_slug(value: str | None, fallback: str = "source", max_length: int = 80) -> str:
    text = (value or "").strip().replace("'", "").replace("’", "")
    text = re.sub(r"[^\w.-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-.").lower()
    if not text:
        text = fallback
    return text[:max_length].strip("-.") or fallback


def resolve_notebooklm_command() -> str:
    command = shutil.which("notebooklm")
    if command:
        return command

    sibling_command = Path(sys.executable).with_name("notebooklm")
    if sibling_command.is_file():
        return str(sibling_command)

    return "notebooklm"


def get_async_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        print("❌ Playwright 未安装")
        print("请运行: pip install playwright")
        sys.exit(1)


class ZLibraryAutoUploader:
    """Z-Library 自动下载上传器"""

    def __init__(
        self,
        task_id: str | None = None,
        workspace_root: Path | str | None = None,
        chunk_max_words: int = DEFAULT_CHUNK_MAX_WORDS,
        upload_timeout_seconds: int = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
    ):
        self.task_id = safe_slug(task_id or uuid.uuid4().hex, fallback="task")
        self.workspace_root = Path(workspace_root) if workspace_root else Path(tempfile.gettempdir()) / "zlibrary-to-notebooklm" / "tasks"
        self.temp_dir = Path(tempfile.gettempdir())
        self.chunk_max_words = max(1, int(chunk_max_words))
        self.upload_timeout_seconds = max(1, int(upload_timeout_seconds))
        self.config_dir = Path.home() / ".zlibrary"
        self.config_file = self.config_dir / "config.json"

    @property
    def task_dir(self) -> Path:
        return self.workspace_root / self.task_id

    @property
    def downloads_dir(self) -> Path:
        return self.task_dir / "downloads"

    def book_workspace(self, file_path: Path) -> tuple[Path, str]:
        slug = safe_slug(file_path.stem, fallback="book")
        workspace = self.task_dir / "books" / slug
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace, slug

    def load_credentials(self) -> dict | None:
        """加载 Z-Library 凭据"""
        if not self.config_file.exists():
            return None

        try:
            import json
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except:
            return None

    async def login_to_zlibrary(self, page):
        """登录 Z-Library"""
        credentials = self.load_credentials()

        if not credentials:
            print("⚠️  未找到 Z-Library 配置")
            print("💡 请先运行: python3 scripts/login.py")
            return False

        print("🔐 登录 Z-Library...")
        print(f"📧 使用账号: {credentials['email']}")

        try:
            # 检查是否已经有登录对话框
            modal = await page.query_selector('#zlibrary-modal-auth')
            if modal:
                print("📝 检测到登录对话框")
                # 直接在对话框中输入
                email_input = await page.wait_for_selector('#modal-auth input[type="email"], #modal-auth input[name="email"]', timeout=5000)
                await email_input.fill(credentials['email'])

                password_input = await page.wait_for_selector('#modal-auth input[type="password"], #modal-auth input[name="password"]', timeout=5000)
                await password_input.fill(credentials['password'])

                # 点击登录
                submit_button = await page.wait_for_selector('#modal-auth button[type="submit"]', timeout=5000)
                await submit_button.click()
            else:
                # 点击登录按钮
                login_button = await page.wait_for_selector('a:has-text("Log in"), a:has-text("登录")', timeout=5000)
                await login_button.click()
                await asyncio.sleep(2)

                # 输入邮箱
                email_input = await page.wait_for_selector('input[type="email"], input[name="email"]', timeout=5000)
                await email_input.fill(credentials['email'])

                # 输入密码
                password_input = await page.wait_for_selector('input[type="password"], input[name="password"]', timeout=5000)
                await password_input.fill(credentials['password'])

                # 点击登录
                submit_button = await page.wait_for_selector('button[type="submit"], button:has-text("Log in"), button:has-text("登录")', timeout=5000)
                await submit_button.click()

            # 等待登录完成
            await asyncio.sleep(5)

            # 检查是否登录成功
            current_url = page.url
            page_content = await page.content()

            if "logout" in page_content.lower() or "登录" not in page_content:
                print("✅ 登录成功")
                return True
            else:
                print("❌ 登录可能失败，请检查账号密码")
                return False

        except Exception as e:
            print(f"❌ 登录过程出错: {e}")
            return False

    async def download_from_zlibrary(self, url: str) -> tuple[Path | None, str | None]:
        """从 Z-Library 下载书籍"""
        print("="*70)
        print("🌐 启动浏览器自动化下载")
        print("="*70)

        # 检查是否有保存的会话
        storage_state = self.config_dir / "storage_state.json"

        if not storage_state.exists():
            print("❌ 未找到会话状态")
            print("💡 请先运行: python3 scripts/login.py")
            return None, None

        print(f"✅ 使用已保存的会话")
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        async with get_async_playwright()() as p:
            # 启动浏览器（使用持久化上下文）
            print("🚀 启动浏览器...")
            launch_choice = choose_chromium_launch_options(p.chromium)
            if launch_choice.log:
                print(f"ℹ️  {launch_choice.log}")

            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(self.config_dir / "browser_profile"),
                headless=True,
                accept_downloads=True,
                downloads_path=str(self.downloads_dir),
                args=['--disable-blink-features=AutomationControlled'],
                **launch_choice.options,
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()
            page.set_default_timeout(60000)

            try:
                # 访问目标页面
                print(f"📖 访问书籍页面...")
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)

                print("⏳ 等待页面加载...")
                await asyncio.sleep(5)

                # 步骤1: 查找下载方式（优先 PDF，然后 EPUB）
                print("🔍 步骤1: 查找下载方式...")

                # 首先检查是否有三个点的菜单按钮（新界面）
                dots_button = await page.query_selector('button[aria-label="更多选项"], button[title="更多"], .more-options, [class*="dots"], [class*="more"]')

                download_link = None
                downloaded_format = None

                if dots_button:
                    print("📱 检测到新版界面（三点菜单）")
                    # 点击打开菜单
                    await dots_button.click()
                    await asyncio.sleep(2)

                    # 查找 PDF 选项（优先）
                    print("🔍 查找 PDF 选项...")
                    pdf_options = await page.query_selector_all('a:has-text("PDF"), button:has-text("PDF")')
                    if pdf_options:
                        # 选择第一个 PDF（通常文件最小）
                        download_link = pdf_options[0]
                        downloaded_format = 'pdf'
                        print(f"✅ 找到 PDF 选项")
                    else:
                        # 备选：查找 EPUB
                        print("🔍 未找到 PDF，查找 EPUB 选项...")
                        epub_options = await page.query_selector_all('a:has-text("EPUB"), button:has-text("EPUB")')
                        if epub_options:
                            download_link = epub_options[0]
                            downloaded_format = 'epub'
                            print(f"✅ 找到 EPUB 选项")

                else:
                    # 旧界面：检查转换按钮
                    print("📱 检测到旧版界面")
                    convert_selector_pdf = 'a[data-convert_to="pdf"]'
                    convert_selector_epub = 'a[data-convert_to="epub"]'

                    # 优先尝试 PDF
                    convert_button = await page.query_selector(convert_selector_pdf)

                    if convert_button:
                        print("📝 检测到 PDF 转换按钮")
                        downloaded_format = 'pdf'
                        await convert_button.evaluate('el => el.click()')
                        print("✅ 已点击 PDF 转换按钮")

                        # 等待转换完成
                        print("⏳ 等待 PDF 转换完成...")
                        for i in range(60):
                            await asyncio.sleep(1)
                            try:
                                message = await page.query_selector('.message:has-text("转换为")')
                                if message:
                                    message_text = await message.inner_text()
                                    if 'pdf' in message_text.lower() and '完成' in message_text:
                                        print("✅ PDF 转换已完成!")
                                        break
                            except:
                                pass
                            if i % 10 == 0 and i > 0:
                                print(f"   ⏳ 等待中... {i}秒")

                        # 查找下载链接
                        download_link = await page.query_selector('a[href*="/dl/"][href*="convertedTo=pdf"]')

                        if not download_link:
                            all_links = await page.query_selector_all('a[href*="/dl/"]')
                            if all_links:
                                download_link = all_links[0]
                                href = await download_link.get_attribute('href')
                                print(f"✅ 找到下载链接: {href}")

                    else:
                        # 备选：尝试 EPUB
                        convert_button = await page.query_selector(convert_selector_epub)

                        if convert_button:
                            print("📝 检测到 EPUB 转换按钮")
                            downloaded_format = 'epub'
                            await convert_button.evaluate('el => el.click()')
                            print("✅ 已点击 EPUB 转换按钮")

                            # 等待转换完成
                            print("⏳ 等待 EPUB 转换完成...")
                            for i in range(60):
                                await asyncio.sleep(1)
                                try:
                                    message = await page.query_selector('.message:has-text("转换为")')
                                    if message:
                                        message_text = await message.inner_text()
                                        if 'epub' in message_text.lower() and '完成' in message_text:
                                            print("✅ EPUB 转换已完成!")
                                            break
                                except:
                                    pass
                                if i % 10 == 0 and i > 0:
                                    print(f"   ⏳ 等待中... {i}秒")

                            # 查找下载链接
                            download_link = await page.query_selector('a[href*="/dl/"][href*="convertedTo=epub"]')

                            if not download_link:
                                all_links = await page.query_selector_all('a[href*="/dl/"]')
                                if all_links:
                                    download_link = all_links[0]
                                    href = await download_link.get_attribute('href')
                                    print(f"✅ 找到下载链接: {href}")

                # 如果还是没找到，尝试直接下载链接
                if not download_link:
                    print("🔍 未检测到转换按钮，查找直接下载链接...")

                    selectors = [
                        'a[href*="/dl/"]',
                        'a:has-text("下载")',
                        'a:has-text("Download")',
                        'button:has-text("下载")',
                    ]

                    for selector in selectors:
                        try:
                            links = await page.query_selector_all(selector)
                            if links:
                                for link in links:
                                    href = await link.get_attribute('href')
                                    if href and '/dl/' in href:
                                        download_link = link
                                        # 从 URL 判断格式
                                        if 'pdf' in href.lower():
                                            downloaded_format = 'pdf'
                                        elif 'epub' in href.lower():
                                            downloaded_format = 'epub'
                                        print(f"✅ 找到下载链接: {href} (格式: {downloaded_format})")
                                        break
                                if download_link:
                                    break
                        except:
                            continue

                if not download_link:
                    print("❌ 未找到下载链接")
                    await browser.close()
                    return None, None

                # 点击下载
                print("⬇️  步骤2: 点击下载链接...")

                try:
                    async with page.expect_download(timeout=DEFAULT_DOWNLOAD_EVENT_TIMEOUT_MS) as download_info:
                        await download_link.evaluate('el => el.click()')
                    print("✅ 点击成功")
                    download = await download_info.value
                    print("⏳ 步骤3: 等待下载完成...")
                    print("✅ 检测到下载开始...")
                    suggested_filename = download.suggested_filename
                    print(f"📄 文件名: {suggested_filename}")
                    download_path = self.downloads_dir / suggested_filename
                    await download.save_as(download_path)
                    print(f"💾 已保存: {download_path}")
                    if not downloaded_format and download_path.suffix:
                        downloaded_format = download_path.suffix.lower().lstrip(".")
                except Exception as e:
                    print(f"❌ 下载启动或保存失败: {e}")
                    await browser.close()
                    return None, None

                # 检查结果
                if download_path and download_path.exists():
                    file_size = download_path.stat().st_size / 1024
                    print(f"✅ 下载成功!")
                    print(f"   格式: {downloaded_format.upper() if downloaded_format else '未知'}")
                    print(f"   文件: {download_path.name}")
                    print(f"   路径: {download_path}")
                    print(f"   大小: {file_size:.1f} KB")
                    await browser.close()
                    return download_path, downloaded_format

                # 备选：检查下载目录
                print("🔍 检查下载目录...")

                # 根据格式查找文件
                if downloaded_format == 'pdf':
                    pattern = "*.pdf"
                else:
                    pattern = "*.epub"

                downloaded_files = list(self.downloads_dir.glob(pattern))

                if downloaded_files:
                    latest_file = max(downloaded_files, key=lambda p: p.stat().st_mtime)
                    file_age = time.time() - latest_file.stat().st_mtime

                    if file_age < 120:
                        file_size = latest_file.stat().st_size / 1024
                        print(f"✅ 下载成功!")
                        print(f"   格式: {downloaded_format.upper() if downloaded_format else '未知'}")
                        print(f"   文件: {latest_file.name}")
                        print(f"   路径: {latest_file}")
                        print(f"   大小: {file_size:.1f} KB")
                        await browser.close()
                        return latest_file, downloaded_format

                print("❌ 未找到下载的文件")
                await browser.close()
                return None, None

            except Exception as e:
                print(f"❌ 下载失败: {e}")
                import traceback
                traceback.print_exc()
                await browser.close()
                return None, None

    def download_from_zlibrary_with_page(self, page, url: str) -> tuple[Path | None, str | None]:
        """Use an already managed Playwright page to download a Z-Library file."""
        print("="*70)
        print("🌐 使用托管浏览器下载")
        print("="*70)

        storage_state = self.config_dir / "storage_state.json"
        if not storage_state.exists():
            print("❌ 未找到会话状态")
            print("💡 请先运行: python3 scripts/login.py")
            return None, None

        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        page.set_default_timeout(60000)
        print("📖 访问书籍页面...")
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        time.sleep(3)

        downloaded_format = None
        download_link = None
        dots_button = page.query_selector('button[aria-label="更多选项"], button[title="更多"], .more-options, [class*="dots"], [class*="more"]')
        if dots_button:
            print("📱 检测到新版界面（三点菜单）")
            dots_button.click()
            time.sleep(1)
            pdf_options = page.query_selector_all('a:has-text("PDF"), button:has-text("PDF")')
            epub_options = page.query_selector_all('a:has-text("EPUB"), button:has-text("EPUB")')
            if pdf_options:
                download_link = pdf_options[0]
                downloaded_format = 'pdf'
            elif epub_options:
                download_link = epub_options[0]
                downloaded_format = 'epub'
        else:
            for file_format, selector in (('pdf', 'a[data-convert_to="pdf"]'), ('epub', 'a[data-convert_to="epub"]')):
                convert_button = page.query_selector(selector)
                if not convert_button:
                    continue
                downloaded_format = file_format
                convert_button.evaluate('el => el.click()')
                for _ in range(60):
                    time.sleep(1)
                    with contextlib.suppress(Exception):
                        message = page.query_selector('.message:has-text("转换为")')
                        if message and file_format in message.inner_text().lower() and '完成' in message.inner_text():
                            break
                download_link = page.query_selector(f'a[href*="/dl/"][href*="convertedTo={file_format}"]')
                if download_link:
                    break

        if not download_link:
            for selector in ('a[href*="/dl/"]', 'a:has-text("下载")', 'a:has-text("Download")', 'button:has-text("下载")'):
                links = page.query_selector_all(selector)
                for link in links:
                    href = link.get_attribute('href')
                    if href and '/dl/' in href:
                        download_link = link
                        if 'pdf' in href.lower():
                            downloaded_format = 'pdf'
                        elif 'epub' in href.lower():
                            downloaded_format = 'epub'
                        break
                if download_link:
                    break

        if not download_link:
            print("❌ 未找到下载链接")
            return None, None

        try:
            with page.expect_download(timeout=DEFAULT_DOWNLOAD_EVENT_TIMEOUT_MS) as download_info:
                download_link.evaluate('el => el.click()')
            download = download_info.value
            suggested_filename = download.suggested_filename
            download_path = self.downloads_dir / suggested_filename
            download.save_as(download_path)
            if not downloaded_format and download_path.suffix:
                downloaded_format = download_path.suffix.lower().lstrip(".")
            print(f"💾 已保存: {download_path}")
            return download_path, downloaded_format
        except Exception as e:
            print(f"❌ 下载启动或保存失败: {e}")
            return None, None

    def count_words(self, text: str) -> int:
        """统计中英文单词数"""
        import re
        # 匹配中文字符
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        # 匹配英文单词
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
        return chinese_chars + english_words

    def _paragraph_units(self, text: str) -> list[str]:
        parts = re.split(r'(\n{2,})', text)
        units = []
        for index in range(0, len(parts), 2):
            body = parts[index]
            separator = parts[index + 1] if index + 1 < len(parts) else ""
            unit = body + separator
            if unit:
                units.append(unit)
        return units

    def _split_by_word_limit(self, text: str, max_words: int) -> list[str]:
        tokens = list(re.finditer(r'[\u4e00-\u9fff]|\b[a-zA-Z]+\b', text))
        if not tokens:
            return [text]

        fragments = []
        start = 0
        for token_start in range(0, len(tokens), max_words):
            token_end = min(token_start + max_words, len(tokens))
            end = len(text) if token_end == len(tokens) else tokens[token_end - 1].end()
            fragment = text[start:end]
            if fragment:
                fragments.append(fragment)
            start = end
        return fragments

    def _iter_chunk_units(self, content: str, max_words: int):
        chapters = re.split(r'(?=\n#{1,3}\s)', content)
        for chapter in chapters:
            if not chapter:
                continue

            if self.count_words(chapter) <= max_words:
                yield chapter
                continue

            for paragraph in self._paragraph_units(chapter):
                if self.count_words(paragraph) <= max_words:
                    yield paragraph
                else:
                    yield from self._split_by_word_limit(paragraph, max_words)

    def split_markdown_file(self, file_path: Path, max_words: int = 350000) -> list[Path]:
        """分割大 Markdown 文件为多个小文件"""
        print(f"📊 文件过大，开始分割...")
        max_words = max(1, int(max_words))

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        total_words = self.count_words(content)
        print(f"   总词数: {total_words:,}")
        print(f"   每块最大: {max_words:,} 词")

        chunks = []
        current_parts = []
        current_words = 0

        def flush_current() -> None:
            nonlocal current_parts, current_words
            chunk = "".join(current_parts).strip()
            if chunk:
                chunks.append(chunk + "\n")
            current_parts = []
            current_words = 0

        for unit in self._iter_chunk_units(content, max_words):
            unit_words = self.count_words(unit)
            if unit_words == 0:
                if current_parts:
                    current_parts.append(unit)
                continue

            if current_parts and current_words + unit_words > max_words:
                flush_current()

            current_parts.append(unit)
            current_words += unit_words

        flush_current()

        workspace, slug = self.book_workspace(file_path)
        parts_dir = workspace / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        # 写入文件
        chunk_files = []
        total_chunks = len(chunks)
        for i, chunk in enumerate(chunks, 1):
            chunk_file = parts_dir / f"{slug}_part_{i:03d}_of_{total_chunks:03d}.md"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                f.write(chunk)
            chunk_files.append(chunk_file)
            chunk_words = self.count_words(chunk)
            print(f"   ✅ Part {i}/{len(chunks)}: {chunk_words:,} 词")

        return chunk_files

    def convert_to_txt(self, file_path: Path, file_format: str = None) -> Path | list[Path]:
        """转换文件为 TXT 或直接使用 PDF"""
        print("")
        print("="*70)
        print("📝 处理文件")
        print("="*70)

        file_ext = file_path.suffix.lower()

        # 如果是 PDF，直接使用（方案 A）
        if file_ext == '.pdf' or file_format == 'pdf':
            print("✅ 检测到 PDF 格式，直接使用")
            print(f"   文件: {file_path.name}")
            file_size = file_path.stat().st_size if file_path.exists() else 0
            print(f"   大小: {file_size / 1024 / 1024:.1f} MB")
            if file_size > LARGE_DIRECT_UPLOAD_WARNING_BYTES:
                print("⚠️  PDF 超过 200 MB，当前不会自动切分；如果 NotebookLM 拒绝上传，请改用 EPUB/Markdown")
            return file_path

        if file_ext in TEXT_SOURCE_EXTENSIONS:
            word_count = self.count_words(file_path.read_text(encoding='utf-8'))
            print(f"📊 词数统计: {word_count:,}")
            if word_count > self.chunk_max_words:
                print(f"⚠️  文本超过 {self.chunk_max_words:,} 词，开始分片")
                return self.split_markdown_file(file_path, self.chunk_max_words)
            return file_path

        workspace, slug = self.book_workspace(file_path)
        md_file = workspace / f"{slug}.md"

        # 如果是 EPUB，转换为 Markdown
        if file_ext == '.epub':
            print("📖 检测到 EPUB 格式，转换为 Markdown...")
            # 获取脚本所在目录
            script_dir = Path(__file__).parent
            convert_script = script_dir / "convert_epub.py"

            import subprocess
            result = subprocess.run(
                [sys.executable, str(convert_script), str(file_path), str(md_file)],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                print(f"❌ 转换失败: {result.stderr}")
                return file_path

            print(f"✅ 转换成功: {md_file}")

            # 检查文件大小，如果过大则分割
            word_count = self.count_words(md_file.read_text(encoding='utf-8'))
            print(f"📊 词数统计: {word_count:,}")

            if word_count > self.chunk_max_words:
                print(f"⚠️  文件超过 {self.chunk_max_words:,} 词（NotebookLM CLI 限制）")
                return self.split_markdown_file(md_file, self.chunk_max_words)
            else:
                return md_file

        else:
            print(f"ℹ️  文件格式: {file_ext}，直接使用")
            return file_path

    def _create_notebook(self, title: str) -> str | None:
        import subprocess
        import json

        result = subprocess.run(
            [resolve_notebooklm_command(), "create", title, "--json"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return None

        try:
            data = json.loads(result.stdout)
            return data['notebook']['id']
        except:
            return None

    def _upload_source_to_notebook(
        self,
        file_path: Path,
        notebook_id: str | None = None,
        title: str | None = None,
    ) -> tuple[bool, str]:
        import subprocess
        import json

        source_path = Path(file_path).resolve()
        command = [resolve_notebooklm_command(), "source", "add", str(source_path)]
        if notebook_id:
            command.extend(["--notebook", notebook_id])
        if title:
            command.extend(["--title", title])
        command.extend(["--timeout", str(self.upload_timeout_seconds)])
        command.append("--json")
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip() or "notebooklm source add failed"

        try:
            data = json.loads(result.stdout)
            return True, data['source']['id']
        except:
            return False, "解析来源 ID 失败"

    def _title_from_path(self, file_path: Path) -> str:
        stem = re.sub(r"_part_\d{3}_of_\d{3}$", "", file_path.stem)
        stem = re.sub(r"_part\d+$", "", stem)
        title = re.sub(r"[_-]+", " ", stem).strip()
        return title or file_path.stem

    def upload_to_notebooklm(self, file_path: Path | list[Path], title: str = None, notebook_id: str = None) -> dict:
        """上传到 NotebookLM"""
        print("")
        print("="*70)
        print("⬆️  上传到 NotebookLM")
        print("="*70)

        # 处理文件列表（分割后的文件）
        if isinstance(file_path, list):
            print(f"📦 检测到 {len(file_path)} 个文件分块")

            # 使用第一个文件确定书名
            first_file = file_path[0]
            if not title:
                title = self._title_from_path(first_file)
                # 清理文件名
                title = re.sub(r'\[.*?\]', '', title)
                title = re.sub(r'\(.*?\)', '', title)
                title = re.sub(r'\s+', ' ', title).strip()
                if len(title) > 50:
                    title = title[:50] + "..."

            if notebook_id:
                print(f"📚 使用已有笔记本 (ID: {notebook_id[:8]}...)")
            else:
                print(f"📚 创建笔记本: {title}")
                notebook_id = self._create_notebook(title)
                if not notebook_id:
                    return {"success": False, "error": "创建或解析笔记本 ID 失败"}
                print(f"✅ 笔记本已创建 (ID: {notebook_id[:8]}...)")

            # 上传所有分块
            source_ids = []
            failed_chunks = []
            for i, chunk_file in enumerate(file_path, 1):
                print(f"📄 上传分块 {i}/{len(file_path)}: {chunk_file.name}")
                source_title = f"{title} - Part {i:03d}/{len(file_path):03d}"
                ok, value = self._upload_source_to_notebook(chunk_file, notebook_id, title=source_title)
                if not ok:
                    print(f"⚠️  分块 {i} 上传失败: {value}")
                    failed_chunks.append({"file": str(chunk_file), "error": value})
                    continue
                source_ids.append(value)
                print(f"   ✅ 成功 (ID: {value[:8]}...)")

            if failed_chunks:
                return {
                    "success": False,
                    "notebook_id": notebook_id,
                    "source_ids": source_ids,
                    "failed_chunks": failed_chunks,
                    "title": title,
                    "chunks": len(file_path),
                    "error": f"分块上传失败: {len(failed_chunks)}/{len(file_path)} 个分块失败",
                }

            return {
                "success": len(source_ids) > 0,
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "title": title,
                "chunks": len(file_path)
            }

        # 单文件上传
        # 确定书名
        if not title:
            title = self._title_from_path(file_path)
            # 清理文件名
            title = re.sub(r'\[.*?\]', '', title)
            title = re.sub(r'\(.*?\)', '', title)
            title = re.sub(r'\s+', ' ', title).strip()
            # 截断过长的书名
            if len(title) > 50:
                title = title[:50] + "..."

        if notebook_id:
            print(f"📚 使用已有笔记本 (ID: {notebook_id[:8]}...)")
        else:
            print(f"📚 创建笔记本: {title}")
            notebook_id = self._create_notebook(title)
            if not notebook_id:
                return {"success": False, "error": "创建或解析笔记本 ID 失败"}
            print(f"✅ 笔记本已创建 (ID: {notebook_id[:8]}...)")

        # 上传文件
        print(f"📄 上传文件...")
        ok, value = self._upload_source_to_notebook(file_path, notebook_id, title=title)
        if not ok:
            return {"success": False, "error": value}

        print(f"✅ 上传成功 (ID: {value[:8]}...)")
        return {
            "success": True,
            "notebook_id": notebook_id,
            "source_id": value,
            "title": title
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments before starting browser automation."""
    parser = argparse.ArgumentParser(
        prog="upload.py",
        description="Z-Library 全自动下载并上传到 NotebookLM",
    )
    parser.add_argument(
        "url",
        metavar="Z-Library URL",
        help="要下载并上传的 Z-Library 书籍页面 URL",
    )
    return parser.parse_args(argv)


async def main():
    """主函数"""
    args = parse_args()
    url = args.url
    uploader = ZLibraryAutoUploader()

    # 下载
    downloaded_file, file_format = await uploader.download_from_zlibrary(url)

    if not downloaded_file or not downloaded_file.exists():
        print("")
        print("="*70)
        print("❌ 下载失败，无法继续")
        print("="*70)
        sys.exit(1)

    # 转换
    final_file = uploader.convert_to_txt(downloaded_file, file_format)

    # 上传
    result = uploader.upload_to_notebooklm(final_file)

    print("")
    print("="*70)
    if result['success']:
        print("🎉 全流程完成！")
        print("="*70)
        print(f"📚 书名: {result['title']}")
        print(f"🆔 笔记本 ID: {result['notebook_id']}")

        # 处理分块上传的结果
        if 'chunks' in result:
            print(f"📦 分块数: {result['chunks']}")
            print(f"📄 成功上传 {len(result['source_ids'])}/{result['chunks']} 个分块")
            print("   来源 IDs:")
            for sid in result['source_ids']:
                print(f"      - {sid}")
        else:
            print(f"📄 来源 ID: {result['source_id']}")

        print("")
        print("💡 下一步:")
        print(f"   notebooklm use {result['notebook_id']}")
        print(f"   notebooklm ask \"这本书的核心观点是什么？\"")
    else:
        print("❌ 上传失败")
        print("="*70)
        print(f"错误: {result.get('error', '未知错误')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
