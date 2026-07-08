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
- 查看、启动、关闭、重启可复用的 Z-Library 自动化浏览器
- 在搜索结果中选择“下载”或“下载并上传”
- 搜索结果会和本地任务 manifest 按规范化后的 Z-Library 书籍键匹配，标出未下载、已下载、已分片、已上传或失败状态
- 查看 NotebookLM 笔记本列表
- 创建 NotebookLM 笔记本
- 选择已有笔记本并上传
- 查看本地已下载文件、处理结果、可上传来源和上传状态
- 在本地文件详情弹窗中处理/分片、上传全部来源或重新上传全部来源，不重新下载
- 查看下载/处理/上传的阶段进度；详细日志默认折叠为右下角按钮，需要排查时再展开日志抽屉

搜索结果与本地文件的主匹配键是规范化后的 Z-Library URL 路径，例如 `https://zh.zlib.li/book/123/title?token=...` 会归一为 `book/123/title`。不同 Z-Library 域名、query 或 hash 不影响匹配。如果同一本书有多个本地任务，工作台默认展示最新任务，并在搜索结果中提示本地份数；再次点击下载会提示用户已有本地文件，确认后会创建新的本地任务，不覆盖旧文件。

下载进度目前是阶段进度，不是字节级下载百分比。原因是 Playwright 的下载保存接口不能稳定提供实时字节数。工作台会显示准备下载、等待下载、保存文件、处理/分片、上传等阶段百分比；如果后续能拿到稳定直链，才适合升级为真实字节进度。

如果下载失败，后端会把任务统一收敛到 `status=failed`、`stage=failed`、`progress.phase=failed`，前端会停止显示“正在下载”，并在当前任务卡中给出失败原因和恢复动作：

- 重试下载：重新创建下载任务
- 重启浏览器：用于处理托管浏览器状态异常、页面卡住或下载事件超时
- 查看日志：展开日志抽屉查看 Playwright 或 Z-Library 页面细节

下载失败但没有生成本地文件时，`GET /api/local-files` 不会返回本地资产；这时搜索结果会用当前任务状态标出“下载失败”，而不是误判为“仍在下载”。下载成功但上传失败时，本地文件仍会出现在本地文件列表，用户应进入详情页选择失败来源或全部来源重传。

前端状态以后端任务和 manifest 为准：

- 任务轮询使用 `GET /api/tasks/<task_id>`，每次返回后都会同步刷新 `GET /api/local-files`
- 任务进入完成或失败后，会额外刷新浏览器状态和登录状态，避免浏览器忙碌、登录失效等状态滞后
- 本地文件详情弹窗不保存独立真相，它会跟随 `GET /api/local-files` 返回的最新资产刷新
- 单分片/批量分片上传按钮可以短暂显示“上传中”，但如果请求失败或后端没有创建任务，前端会重新读取后端状态，避免把本地来源永久标成失败
- 如果后端重启导致内存任务表丢失，`GET /api/tasks/<task_id>` 会从任务目录的 `manifest.json` 恢复任务；`GET /api/tasks` 也会直接扫描 manifest，因此失败但没有生成本地文件的下载任务不会从任务状态里消失

### API 端点

```text
GET  /api/search?q=<关键词>&limit=50
GET  /api/browser/status
GET  /api/notebooks
GET  /api/local-files
GET  /api/tasks
POST /api/browser/start
POST /api/browser/close
POST /api/browser/restart
POST /api/notebooks
POST /api/upload
POST /api/download
POST /api/process-local
POST /api/upload-local
POST /api/upload-source
POST /api/upload-sources
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
{"zlibrary_url":"https://zh.zlib.li/book/..."}
```

```json
{"headless":true,"keep_open":true}
```

```json
{"local_path":"/tmp/zlibrary-to-notebooklm/tasks/<task-id>/downloads/book.pdf","notebook_id":"<notebook-id>"}
```

```json
{"task_id":"<task-id>","local_path":"/tmp/zlibrary-to-notebooklm/tasks/<task-id>/downloads/book.md","strategy":"keep"}
```

```json
{"task_id":"<task-id>","source_paths":["/tmp/zlibrary-to-notebooklm/tasks/<task-id>/books/book/parts/book_part_001_of_003.md"],"notebook_id":"<notebook-id>"}
```

### 本地文件和断点重试

每个上传任务都会写入独立工作目录：

```text
/tmp/zlibrary-to-notebooklm/tasks/<task-id>/
├── manifest.json
├── downloads/          # 原始 PDF/EPUB/其他下载文件
└── books/<book-slug>/  # EPUB 转出的 Markdown 和分块文件
```

`manifest.json` 记录任务阶段、阶段进度、规范化书籍键、下载文件、转换文件、分片列表、NotebookLM 目标、上传记录和失败原因。Web/VSCode 工作台通过 `GET /api/local-files` 扫描这些 manifest，并返回统一的 `upload_sources` 视图，因此即使上传失败，也能在“本地文件”区域看到已下载文件和每个可上传来源的状态。每个来源还会带上自己的 `upload_records`，用于在详情页按分片折叠查看上传历史、目标知识库、source id 和失败原因。

本地文件详情弹窗用于恢复和排查：

- 原始文件：`downloads/` 中的 PDF/EPUB/其他下载文件
- 处理结果：PDF/单文件直接作为 1 个来源，EPUB 转出的 Markdown 或超过词数阈值后生成多个来源
- 可上传来源：每个来源的文件名、大小、上传状态、source id 或失败原因
- 本次目标：详情弹窗内可重新选择已有知识库或输入新知识库名，不依赖主页面当前选择
- 批量上传：可全选可传来源、只选失败、只选未完成，也可以单独上传某个来源
- 上传记录：默认折叠在每个来源下，需要查看某个分片历史时再展开

如果下载已成功但上传失败，优先在详情弹窗点击“只选失败”再“上传已选”，这会调用 `POST /api/upload-sources`。如果只想验证某一个分片，可在来源列表里点击“单传”，这会调用 `POST /api/upload-source`。如果还没有处理结果，可先点击“处理/分片”。如果已经处理/分片过，再次处理必须选择策略：`keep` 保留现有分片，`replace` 覆盖当前处理结果，`version` 生成新版本处理结果；上传现有来源不会重新下载，也不会静默重新转换或重新分片。

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
   - 启动、关闭、重启托管浏览器
   - 刷新 NotebookLM 知识库
   - 创建新知识库
   - 上传到 NotebookLM
   - 查看本地文件和重试失败上传
   - 轮询任务日志和结果

插件停止后端或 VSCode 退出时，会先调用 `POST /api/browser/close` 并传入强制关闭参数，让后端优雅关闭托管浏览器，再终止 Python 后端进程。如果 VSCode 异常退出导致通知没有送达，后端浏览器会在空闲超时后自动关闭。

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
