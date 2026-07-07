---
name: zlibrary-to-notebooklm
description: 自动从 Z-Library 搜索、下载书籍并上传到 Google NotebookLM。支持 PDF/EPUB、自动转换、分块上传，并提供可选本地 Web 工作台。
---

# Z-Library to NotebookLM Skill

让 Claude 帮用户把合法可访问的 Z-Library 资料下载到本地，并上传到 NotebookLM，用于基于原文的阅读、摘要和问答。

## 🎯 核心功能

- 根据 Z-Library 链接一键下载并上传
- 可先用关键词搜索书籍链接
- 优先下载 PDF，保留原始排版
- EPUB 自动转换为 Markdown
- 超大 Markdown 自动按约 350k 词分块
- 自动创建 NotebookLM 笔记本并上传来源
- 可选启动本地 Web 工作台完成搜索、选库和上传

## 📋 激活条件（Triggers）

当用户提到以下需求时，使用此 Skill：

- 用户提供 Z-Library 书籍链接（包含 `zlib.li`、`z-lib.org`、`zh.zlib.li` 等域名）
- 用户说“帮我把这本书上传到 NotebookLM”
- 用户说“自动下载并读这本书”
- 用户说“用 Z-Library 链接创建 NotebookLM 知识库”
- 用户只提供书名或关键词，并希望先搜索可用条目
- 用户想打开本地页面批量选择、创建知识库或上传

## 🔧 核心指令

在执行前，先确认当前目录是本 skill 仓库根目录。如果不是，先进入安装目录，例如：

```bash
cd ~/.claude/skills/zlibrary-to-notebooklm
```

### Step 1: 判断用户输入

从用户请求中提取：

- Z-Library URL（如果已提供）
- 书名、作者或关键词（如果没有 URL）
- 用户是否指定 NotebookLM 笔记本或希望新建笔记本

如果用户只提供关键词，先搜索：

```bash
python3 scripts/search.py "关键词" --limit 20
```

把结果编号、书名和链接返回给用户，请用户确认要处理哪一本。

### Step 2: 检查登录状态

Z-Library 会话保存在：

```text
~/.zlibrary/storage_state.json
```

如果会话不存在或失效，提示用户运行：

```bash
python3 scripts/login.py
```

NotebookLM CLI 也需要提前登录：

```bash
notebooklm login
```

如果 `notebooklm login` 不可用，请让用户运行 `notebooklm --help`，按当前 CLI 版本显示的登录或授权命令操作。

### Step 3: 下载并上传

标准入口始终使用上传脚本：

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

脚本会自动完成：

1. 使用已保存的 Z-Library 会话打开书籍页面
2. 优先下载 PDF，无法获取时降级 EPUB
3. EPUB 转换为 Markdown
4. 超大 Markdown 自动分块
5. 调用 `notebooklm create` 创建笔记本
6. 调用 `notebooklm source add --notebook <id>` 上传来源
7. 返回 NotebookLM 笔记本 ID 和来源 ID

### Step 4: 可选 Web 工作台

如果用户希望在页面中搜索、选择已有 NotebookLM 笔记本或创建新笔记本：

```bash
python3 scripts/web_api.py
```

打开：

```text
http://127.0.0.1:7860
```

首次使用 Web 工作台前，需要构建前端：

```bash
cd web
pnpm install
pnpm build
cd ..
```

前端需要 Node.js `^20.19.0` 或 `>=22.12.0`，以及 `pnpm`。

### Step 5: 返回结果

向用户返回：

- 下载和上传是否成功
- NotebookLM 笔记本 ID
- 来源 ID 或分块来源 ID
- 下一步可执行的 NotebookLM 命令
- 2-3 个适合这本书的后续提问建议

### Step 6: 错误处理

如果遇到错误：

- 登录失败：提示运行 `python3 scripts/login.py` 或 `notebooklm login`
- 找不到 `notebooklm`：提示先确认 `notebooklm --version` 可用
- 搜索无结果：建议换关键词或提供完整 Z-Library 链接
- 下载失败：提示检查登录状态、网络和书籍页面是否可访问
- 上传失败：检查 NotebookLM CLI 登录、文件大小和格式
- 依赖缺失：提示运行 `pip install -r requirements.txt`

不要凭空声称上传成功；必须以脚本输出的 notebook/source ID 为准。

## ⚠️ 重要限制

**仅限合法资源。**

- ✅ 用户拥有合法访问权限的资源
- ✅ 公共领域或开源许可的文档
- ✅ 用户个人拥有版权或已获授权的内容
- ❌ 不要鼓励或协助版权侵权行为

如果 URL 明显涉及受版权保护的商业作品，提醒用户：

> 请确保你有合法访问权限。本项目仅用于学习、研究和技术演示目的，请支持正版阅读。

## 🛠️ 依赖工具

### 必需工具

1. **Python 3.8+**
2. **Playwright** - 浏览器自动化，需要运行 `playwright install chromium`
3. **ebooklib** - EPUB 处理
4. **beautifulsoup4 + lxml** - 搜索结果和 EPUB HTML 解析
5. **NotebookLM CLI** - `notebooklm create`、`notebooklm list`、`notebooklm source add`

### 可选工具

1. **Node.js + pnpm** - 构建 React/Vite Web 工作台

### 配置文件

- `~/.zlibrary/storage_state.json` - Z-Library 登录会话
- `~/.zlibrary/browser_profile/` - Playwright 浏览器数据
- `~/Downloads/` - 原始下载文件
- `/tmp/` - EPUB 转换后的 Markdown 和分块文件

## 📝 使用示例

### 用户提供链接

用户：

```text
帮我把这本书上传到 NotebookLM：
https://zh.zlib.li/book/25314781/aa05a1/钱的第四维
```

执行：

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/25314781/aa05a1/钱的第四维"
```

返回：

```text
✅ 下载并上传成功
📚 笔记本 ID: <notebook-id>
📄 来源 ID: <source-id>

你可以继续问：
- 这本书的核心观点是什么？
- 作者如何论证主要结论？
- 哪些章节适合做成读书笔记？
```

### 用户只提供书名

用户：

```text
帮我找《认知觉醒》并上传到 NotebookLM
```

执行：

```bash
python3 scripts/search.py "认知觉醒" --limit 20
```

把搜索结果展示给用户，确认链接后再运行 `scripts/upload.py`。

### 用户想使用页面

执行：

```bash
python3 scripts/web_api.py
```

让用户打开 `http://127.0.0.1:7860`。

## 🔄 备选流程

### 如果用户提供本地文件

本 Skill 主要处理 Z-Library 链接。对于本地文件，建议用户直接使用 NotebookLM CLI：

```bash
notebooklm source add "文件路径" --notebook "<notebook-id>"
```

如果用户还没有笔记本：

```bash
notebooklm create "笔记本名称" --json
```

### 如果用户有多个链接

逐个处理，避免并发浏览器会话或下载任务互相影响：

```bash
for url in "url1" "url2" "url3"; do
    python3 scripts/upload.py "$url"
    sleep 5
done
```

## 🚨 故障排查

**Q: 提示“未找到登录会话”**

A: 运行 `python3 scripts/login.py`，完成 Z-Library 登录。

**Q: 提示“未找到 notebooklm 命令”**

A: 先确认 `notebooklm --version` 可用，并运行 `notebooklm login`。

**Q: 搜索结果为空**

A: 换关键词、减少限定词，或让用户提供完整 Z-Library 链接。

**Q: 下载失败或找不到下载按钮**

A: 检查浏览器窗口、登录状态和书籍页面结构；页面变化时可能需要手动确认。

**Q: NotebookLM 上传失败**

A: 检查 NotebookLM CLI 登录状态、文件大小、格式和网络。

详细帮助见 `docs/TROUBLESHOOTING.md`。

## 📚 相关资源

- [README](README.md)
- [安装指南](INSTALL.md)
- [工作流程详解](docs/WORKFLOW.md)
- [故障排除指南](docs/TROUBLESHOOTING.md)
- [NotebookLM](https://notebooklm.google.com/)
- [Z-Library](https://zh.zlib.li/)
- [Playwright 文档](https://playwright.dev/)
- [项目 GitHub](https://github.com/wei-ze-guang/zlibrary-to-notebooklm)

---

**Skill Version:** 1.0.0

**Last Updated:** 2026-07-07
