# 工作流程详解

本文说明当前项目的四条使用链路：

- CLI 主流程：`login.py` → `search.py`（可选）→ `upload.py`
- Web 工作台：`web_api.py` + `web/` 前端
- VSCode 插件工作台：`vscode-extension/` 自动启动 `web_api.py` 并在 Webview 中打开同一套前端
- NotebookLM CLI：由脚本调用 `notebooklm create/list/source add`

## 完整流程图

```text
┌─────────────────────────────────────────────────────────────┐
│                    Z-Library to NotebookLM                   │
│                        当前工作流程                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
        ┌───────────────────────────────────────┐
        │  1. 用户输入书名关键词或 Z-Library URL │
        └───────────────────────────────────────┘
                     ↙              ↘
             只有关键词              已有 URL
                 ↓                      ↓
    ┌──────────────────┐      ┌─────────────────┐
    │ scripts/search.py │      │ scripts/upload.py│
    │ 展示候选链接      │      │ 进入上传流程     │
    └──────────────────┘      └─────────────────┘
                 ↓                      ↓
        ┌───────────────────────────────────────┐
        │  2. 检查 Z-Library 会话                │
        │     ~/.zlibrary/storage_state.json     │
        └───────────────────────────────────────┘
                     ↙              ↘
              会话存在              会话不存在
                 ↓                      ↓
    ┌──────────────────┐      ┌─────────────────┐
    │ 使用已保存的会话  │      │ python3 scripts/ │
    │ 启动 Playwright   │      │ login.py         │
    └──────────────────┘      └─────────────────┘
                 ↓
        ┌───────────────────────────────────────┐
        │  3. 访问书籍页面并选择格式             │
        │     优先级: PDF > EPUB > Markdown/TXT  │
        └───────────────────────────────────────┘
                 ↓
        ┌───────────────────────────────────────┐
        │  4. 下载到任务隔离工作目录              │
        └───────────────────────────────────────┘
                 ↓
        ┌───────────────────────────────────────┐
        │  5. 格式处理                           │
        │     PDF 直接上传                       │
        │     EPUB 转 Markdown                   │
        │     Markdown/TXT >350k 词自动分块       │
        └───────────────────────────────────────┘
                 ↓
        ┌───────────────────────────────────────┐
        │  6. 调用 NotebookLM CLI                │
        │     create / source add --notebook     │
        └───────────────────────────────────────┘
                 ↓
        ┌───────────────────────────────────────┐
        │  7. 返回 notebook_id 和 source_id       │
        └───────────────────────────────────────┘
                 ↓
                      ✅ 完成
```

## CLI 流程

### 1. 登录 NotebookLM CLI

```bash
notebooklm login
```

如果当前 `notebooklm` 版本没有 `login` 子命令，运行 `notebooklm --help` 查看实际的登录或授权命令。

### 2. 登录 Z-Library

```bash
python3 scripts/login.py
```

脚本会打开浏览器，用户在浏览器中完成登录后回到终端按 ENTER。会话保存到：

```text
~/.zlibrary/storage_state.json
~/.zlibrary/browser_profile/
```

### 3. 搜索书籍（可选）

```bash
python3 scripts/search.py "机器学习" --limit 20
```

搜索脚本会：

- 使用已保存的 Z-Library 会话
- 打开搜索页
- 解析书名、简要信息和链接
- 输出可复制的 Z-Library 书籍 URL

### 4. 下载并上传

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

`upload.py` 是主入口。它负责下载、转换、分块、创建 NotebookLM 笔记本和上传来源。

## 下载与格式处理

登录流程使用可视浏览器；搜索和下载默认使用无头浏览器复用已保存的 Z-Library 会话，避免每次搜索/下载都弹出窗口。

### 页面识别

脚本会兼容两类页面：

- 新版界面：尝试打开更多菜单，优先选择 PDF，其次 EPUB
- 旧版界面：查找 `data-convert_to="pdf"` 或 `data-convert_to="epub"` 转换按钮

### 下载目录

每个上传任务都会分配独立工作目录，避免并发任务或同名书籍互相覆盖。默认路径为：

```text
/tmp/zlibrary-to-notebooklm/tasks/<task-id>/
```

目录结构如下：

```text
downloads/                         # 原始 PDF/EPUB/其他下载文件
books/<book-slug>/<book-slug>.md    # EPUB 转换后的 Markdown
books/<book-slug>/parts/            # 自动分块文件
```

### 格式优先级

1. **PDF** - 保留排版，直接上传
2. **EPUB** - 转为 Markdown 后上传
3. **Markdown/TXT** - 直接统计词数，超限时分块
4. **其他格式** - 尝试直接上传，失败时需要用户手动处理

### 分块策略

NotebookLM 官方限制通常高于脚本阈值，但 CLI 在大文件场景下容易超时。项目采用更保守的阈值：

```text
350,000 词 / 文本来源
```

当 EPUB 转出的 Markdown，或用户已有的 `.md`、`.markdown`、`.txt` 超过阈值时，脚本会优先按章节、段落拆分；如果单个段落仍超过阈值，会继续按词边界拆分，避免留下超限分块。

分块文件写入当前任务的 `books/<book-slug>/parts/`，命名格式为：

```text
<book-slug>_part_001_of_008.md
<book-slug>_part_002_of_008.md
```

PDF 当前直接上传。超过 200MB 的 PDF 会输出警告，但不会自动拆分；如果 NotebookLM 拒绝上传，需要改用 EPUB/Markdown 或手动压缩、拆分 PDF。

## NotebookLM 上传

脚本通过 `subprocess.run` 调用 NotebookLM CLI，关键命令形态如下：

```bash
notebooklm create "书名" --json
notebooklm source add "文件路径" --notebook "<notebook-id>" --title "来源标题" --timeout 180 --json
```

传给 NotebookLM CLI 的文件路径会先解析为真实路径，避免 macOS `/var`、`/tmp` 这类 symlink 路径被 CLI 拒绝。

如果是 Web 工作台创建的新笔记本，`web_api.py` 会先调用 `notebooklm create`，再把返回的 `notebook_id` 传给上传流程。

分块上传时，来源标题会带上序号，例如 `Book Slug - Part 001/008`。如果任意分块上传失败，任务整体会失败，并返回已成功的 `source_ids` 和失败分块路径，避免用户误以为整本书已经完整上传。

## Web 工作台流程

### 启动

首次使用前构建前端：

```bash
cd web
pnpm install
pnpm build
cd ..
```

启动本地 API 和静态页面：

```bash
python3 scripts/web_api.py
```

打开：

```text
http://127.0.0.1:7860
```

### 页面能力

Web 工作台支持：

- 搜索 Z-Library
- 查看 NotebookLM 笔记本列表
- 创建 NotebookLM 笔记本
- 选择已有笔记本并上传
- 查看本地已下载文件和上传状态
- 上传失败后复用本地文件重试，不重新下载
- 查看上传任务状态和日志

### API 端点

```text
GET  /api/search?q=<关键词>&limit=50
GET  /api/notebooks
GET  /api/local-files
GET  /api/tasks
POST /api/notebooks
POST /api/upload
POST /api/upload-local
GET  /api/tasks/<task_id>
```

请求体示例：

```json
{"title":"我的新知识库"}
```

```json
{"zlibrary_url":"https://zh.zlib.li/book/...","notebook_id":"<notebook-id>"}
```

```json
{"local_path":"/tmp/zlibrary-to-notebooklm/tasks/<task-id>/downloads/book.pdf","notebook_id":"<notebook-id>"}
```

### 本地文件和断点重试

每个上传任务都会写入独立工作目录：

```text
/tmp/zlibrary-to-notebooklm/tasks/<task-id>/
├── manifest.json
├── downloads/          # 原始 PDF/EPUB/其他下载文件
└── books/<book-slug>/  # EPUB 转出的 Markdown 和分块文件
```

`manifest.json` 记录任务阶段、下载文件、转换文件、NotebookLM 目标、上传结果和失败原因。Web/VSCode 工作台通过 `GET /api/local-files` 扫描这些 manifest，因此即使上传失败，也能在“本地文件”区域看到已下载文件，并通过 `POST /api/upload-local` 直接重试上传。

## VSCode 插件流程

插件目录位于 `vscode-extension/`。它不重写业务逻辑，而是复用当前 Web 工作台：

1. 用户在命令面板执行 `Z-Library to NotebookLM: Open Workbench`
2. 插件读取 `zlibraryToNotebooklm.pythonPath`，未配置时使用 `PYTHON` 或 `python3`
3. 插件分配一个空闲 localhost 端口
4. 插件运行 `scripts/web_api.py --host 127.0.0.1 --port <port>`
5. 插件打开 VSCode Webview，并通过 iframe 加载 `http://127.0.0.1:<port>`
6. Webview 中的所有按钮继续调用同一套 `/api/*`：
   - Z-Library 登录、完成登录、取消登录
   - NotebookLM 登录、取消登录、刷新状态
   - 搜索书籍和选择结果
   - 刷新 NotebookLM 知识库
   - 创建新知识库
   - 上传到 NotebookLM
   - 查看本地文件和重试失败上传
   - 轮询任务日志和结果

插件额外提供三个命令：

```text
Z-Library to NotebookLM: Open Workbench
Z-Library to NotebookLM: Restart Backend
Z-Library to NotebookLM: Stop Backend
```

开发验证：

```bash
cd web
pnpm build
cd ../vscode-extension
pnpm test
```

也可以用 `notebook_title` 让后端先创建新笔记本：

```json
{"zlibrary_url":"https://zh.zlib.li/book/...","notebook_title":"新知识库"}
```

## npm 脚本快捷方式

根目录 `package.json` 提供了同名快捷命令：

```bash
npm run login
npm run search -- "机器学习"
npm run upload -- "https://zh.zlib.li/book/..."
npm run web
```

这些命令只是调用 `scripts/` 下的 Python 文件，不会替代 Python 依赖安装。

## 故障排除速查

### 会话过期

```bash
rm ~/.zlibrary/storage_state.json
python3 scripts/login.py
```

### NotebookLM CLI 未登录

```bash
notebooklm login
```

### 找不到 `notebooklm`

```bash
notebooklm --version
```

如果命令不存在，请先按你使用的 NotebookLM CLI 来源完成安装。

### 找不到下载按钮

- 检查浏览器窗口是否已登录
- 手动打开书籍页面确认是否可下载
- 尝试使用搜索结果里的另一个条目
- 页面结构变化时，需要更新 Playwright 选择器

## 最佳实践

1. **先搜索，后上传**

   ```bash
   python3 scripts/search.py "书名 作者" --limit 20
   ```

2. **批量处理时串行执行**

   ```bash
   for url in "url1" "url2" "url3"; do
       python3 scripts/upload.py "$url"
       sleep 5
   done
   ```

3. **保留原始文件**

   - 原始 PDF/EPUB 在 `/tmp/zlibrary-to-notebooklm/tasks/<task-id>/downloads/`
   - Markdown 和分块文件在 `/tmp/zlibrary-to-notebooklm/tasks/<task-id>/books/<book-slug>/`
   - 上传失败时可以复用这些文件手动排查

4. **修改代码后运行测试**

   ```bash
   python3 -m unittest discover -v
   ```

---

**需要帮助？** 查看 [故障排除指南](TROUBLESHOOTING.md)。
