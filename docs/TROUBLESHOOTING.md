# 故障排查指南

本文档帮助你排查 zlibrary-to-notebooklm 的 CLI、NotebookLM CLI 和 Web 工作台问题。

---

## 🔐 登录问题

### 问题：未找到 Z-Library 会话

**症状：**

```text
❌ 未找到会话状态
💡 请先运行: python3 scripts/login.py
```

**解决方案：**

1. 进入项目根目录：

   ```bash
   cd ~/.claude/skills/zlibrary-to-notebooklm
   ```

   如果你是普通克隆安装，请进入自己的仓库目录。

2. 重新登录 Z-Library：

   ```bash
   python3 scripts/login.py
   ```

3. 验证会话文件：

   ```bash
   ls -lh ~/.zlibrary/storage_state.json
   ```

### 问题：Z-Library 登录失败

**症状：**

- 浏览器打开但无法登录
- 页面提示网络错误
- 登录后脚本仍提示会话不存在

**解决方案：**

1. 检查网络连接：

   ```bash
   curl -I https://zh.zlib.li
   ```

2. 清除旧会话后重试：

   ```bash
   rm ~/.zlibrary/storage_state.json
   python3 scripts/login.py
   ```

3. 确认浏览器中已经完成登录，再回到终端按 ENTER。

### 问题：NotebookLM CLI 未登录

**症状：**

```text
notebooklm create failed
notebooklm list failed
```

**解决方案：**

```bash
notebooklm --version
notebooklm login
```

如果 `notebooklm login` 不可用，请运行 `notebooklm --help`，使用当前版本显示的登录或授权命令。

---

## 🔎 搜索问题

### 问题：搜索提示未找到会话

`scripts/search.py` 同样需要 Z-Library 登录会话。

```bash
python3 scripts/login.py
python3 scripts/search.py "机器学习" --limit 20
```

### 问题：搜索结果为空

**可能原因：**

1. 关键词过窄
2. Z-Library 页面结构变化
3. 网络请求没有完全加载
4. 当前账号或站点没有返回可解析结果

**解决方案：**

```bash
python3 scripts/search.py "书名 作者" --limit 20
python3 scripts/search.py "英文书名" --limit 20
```

如果仍为空，可以手动打开 Z-Library 搜索页，复制目标书籍 URL 后直接运行：

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

---

## 📥 下载问题

### 问题：找不到下载按钮

**症状：**

```text
❌ 未找到下载链接
```

**可能原因：**

1. Z-Library 页面结构变化
2. 登录会话失效
3. 该条目没有可下载格式
4. 网络加载不完整

**解决方案：**

1. 检查会话：

   ```bash
   ls -lh ~/.zlibrary/storage_state.json
   ```

2. 手动打开页面确认是否能下载。

3. 换一个搜索结果条目。

4. 如果页面结构明显变化，需要更新 `scripts/upload.py` 中的 Playwright 选择器。

### 问题：下载超时

**症状：**

```text
⏳ 等待超时
❌ 下载失败
```

**解决方案：**

```bash
curl -I https://zh.zlib.li
python3 scripts/upload.py "你的链接"
```

脚本会等待页面和下载事件。如果网络较慢，可以先手动确认页面可访问，再重试。

### 问题：转换超时

**症状：**

```text
⚠️ 转换超时，尝试继续...
```

**说明：**

Z-Library 的在线格式转换可能需要较长时间。脚本会继续尝试查找下载链接。

**解决方案：**

- 优先选择已有 PDF 的条目
- 换一个 EPUB/PDF 来源
- 手动下载后用 NotebookLM CLI 上传

---

## 📤 上传问题

### 问题：NotebookLM 命令未找到

**症状：**

```text
command not found: notebooklm
未找到 notebooklm 命令，请先安装并运行 notebooklm login
```

**解决方案：**

1. 确认命令是否可用：

   ```bash
   notebooklm --version
   ```

2. 如果命令不存在，请先按你使用的 NotebookLM CLI 来源完成安装。

3. 登录：

   ```bash
   notebooklm login
   ```

4. 重新运行上传：

   ```bash
   python3 scripts/upload.py "https://zh.zlib.li/book/..."
   ```

### 问题：上传失败

**症状：**

```text
✅ 笔记本已创建
❌ 上传失败
```

**可能原因：**

1. NotebookLM CLI 未登录或 token 失效
2. 文件过大导致 CLI 超时
3. 文件格式不支持
4. 网络问题

**解决方案：**

1. 重新登录 NotebookLM：

   ```bash
   notebooklm login
   ```

2. 检查下载文件：

   ```bash
   find /tmp/zlibrary-to-notebooklm/tasks -type f -path '*/downloads/*' 2>/dev/null | tail -20
   ```

3. 在 Web/VSCode 工作台重试本地文件：

   - 打开工作台的“本地文件”区域
   - 找到状态为 `failed` 或已下载的文件
   - 点击“详情”查看原始文件、处理结果、可上传来源、目标知识库和失败原因
   - 如果还没有可上传来源，先点击“处理/分片”
   - 在详情弹窗内选择本次上传的 NotebookLM 知识库
   - 勾选要上传的来源，或点击“只选失败”
   - 点击“上传已选 N”或单个来源右侧的“单传”

   处理/分片会调用 `/api/process-local`，批量上传会调用 `/api/upload-sources`，单个来源上传会调用 `/api/upload-source`，不会重新下载 Z-Library 文件。已有分片再次处理时需要明确选择 `keep`、`replace` 或 `version`；上传已有来源不会静默重新转换或重新分片。

4. 手动上传测试：

   ```bash
   notebooklm source add "文件路径" --notebook "<notebook-id>"
   ```

   如果 NotebookLM CLI 提示 `Path is a symlink`，请确认正在运行最新代码。项目会在调用 CLI 前把 `/var`、`/tmp` 这类 macOS symlink 路径解析为真实路径。

5. 对 EPUB，优先使用脚本转换成 Markdown。EPUB 转出的 Markdown，以及已有 `.md`、`.markdown`、`.txt` 超过约 350k 词时，脚本会自动分块上传。

### 问题：大文件上传不稳定

NotebookLM 官方限制和 CLI 实际稳定范围不完全相同。项目采取保守策略：

- EPUB 转 Markdown 后超过约 350k 词会自动分块
- `.md`、`.markdown`、`.txt` 超过约 350k 词也会自动分块
- 每个分块逐个上传到同一个笔记本，标题会带 `Part 001/008` 这类序号
- 任意分块失败时，任务整体会失败并返回失败分块路径
- PDF 当前直接上传；超过 200MB 会输出警告，如果上传失败需要手动压缩或拆分

---

## 🖥️ Web 工作台问题

### 问题：打开 `http://127.0.0.1:7860` 是空白或旧页面

**解决方案：**

1. 构建前端：

   ```bash
   cd web
   pnpm install
   pnpm build
   cd ..
   ```

2. 启动后端：

   ```bash
   python3 scripts/web_api.py
   ```

3. 刷新浏览器页面。

### 问题：Web 工作台提示 NotebookLM 错误

Web 后端会调用本机的 `notebooklm` 命令。

```bash
notebooklm --version
notebooklm login
python3 scripts/web_api.py
```

如果终端中 `notebooklm` 不可用，Web 工作台也无法列出或创建 NotebookLM 笔记本。

### 问题：上传任务失败但页面没有详细报错

查看页面任务日志，或在终端中直接运行同一个链接：

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

终端输出通常会给出更完整的 Playwright、下载或 NotebookLM CLI 错误。

### 问题：自动化浏览器一直开着或无法关闭

Web/VSCode 工作台会复用一个托管浏览器来减少搜索、下载时的启动成本。正常情况下可以在页面顶部“自动化浏览器”区域点击“关闭”。

- 如果显示“忙碌”，说明当前有搜索或下载任务正在使用浏览器，普通关闭会被拒绝
- 如果 VSCode 退出，插件会先请求后端强制关闭浏览器，再停止后端进程
- 如果 VSCode 异常退出，后端会在空闲超时后自动关闭浏览器
- 如果状态显示“已异常”或“空闲关闭”，点击“重启”即可重新建立上下文

也可以直接调用：

```bash
curl -X POST http://127.0.0.1:7860/api/browser/close \
  -H 'Content-Type: application/json' \
  -d '{"force":true}'
```

---

## 🔧 依赖问题

### 问题：Playwright 未安装

**症状：**

```text
ModuleNotFoundError: No module named 'playwright'
```

**解决方案：**

```bash
pip install -r requirements.txt
playwright install chromium
```

验证：

```bash
python3 -c "from playwright.async_api import async_playwright; print('playwright ok')"
```

### 问题：BeautifulSoup 或 lxml 缺失

**症状：**

```text
ModuleNotFoundError: No module named 'bs4'
ModuleNotFoundError: No module named 'lxml'
```

**解决方案：**

```bash
pip install -r requirements.txt
```

`scripts/search.py` 对 BeautifulSoup 有标准库 fallback，但安装 `beautifulsoup4` 和 `lxml` 后解析更稳定。

### 问题：ebooklib 转换失败

**症状：**

```text
❌ 转换失败: ...
```

**解决方案：**

1. 确认 EPUB 文件存在：

   ```bash
   find /tmp/zlibrary-to-notebooklm/tasks -type f -name '*.epub' 2>/dev/null | tail -20
   ```

2. 手动转换测试：

   ```bash
   python3 scripts/convert_epub.py "EPUB路径" "输出路径.md"
   ```

3. 如果 EPUB 内容异常，优先选择 PDF 条目。

### 问题：浏览器崩溃

**症状：**

```text
Browser crashed: ...
```

**解决方案：**

```bash
playwright install chromium --force
```

如果仍失败，检查系统资源：

```bash
top
```

---

## 📊 配置问题

### 问题：会话频繁失效

**解决方案：**

```bash
ls -l ~/.zlibrary/storage_state.json
chmod 600 ~/.zlibrary/storage_state.json
rm ~/.zlibrary/storage_state.json
python3 scripts/login.py
```

### 问题：下载目录不正确

当前脚本会把每个上传任务隔离到独立工作目录，默认根目录为 `/tmp/zlibrary-to-notebooklm/tasks/`。

查找最近下载文件：

```bash
find /tmp/zlibrary-to-notebooklm/tasks -type f -path '*/downloads/*' 2>/dev/null | tail -20
```

查看任务 manifest：

```bash
find /tmp/zlibrary-to-notebooklm/tasks -name manifest.json 2>/dev/null | tail -20
```

### 问题：Markdown 或分块文件找不到

EPUB 转换后的 Markdown 和分块文件默认在任务工作目录：

```bash
find /tmp/zlibrary-to-notebooklm/tasks -path '*/books/*' -type f 2>/dev/null | tail -20
```

---

## 📝 Skill 使用问题

### 问题：Claude 无法识别 Skill

**解决方案：**

1. 确认 `SKILL.md` 存在：

   ```bash
   ls -l ~/.claude/skills/zlibrary-to-notebooklm/SKILL.md
   ```

2. 检查权限：

   ```bash
   chmod 644 ~/.claude/skills/zlibrary-to-notebooklm/SKILL.md
   ```

3. 重启 Claude Code。

4. 使用明确触发词：

   ```text
   用 zlibrary-to-notebooklm skill 处理这个 Z-Library 链接：...
   ```

---

## 🆘 仍然无法解决？

### 收集诊断信息

```bash
python3 --version
notebooklm --version
python3 -m unittest discover -v
pip list | grep -E "playwright|ebooklib|beautifulsoup4|bs4|lxml"
```

请同时保留：

- 完整终端错误信息
- Z-Library 链接
- 你执行过的命令
- 预期结果和实际结果
- Web 工作台任务日志（如果使用 Web）

### 获取帮助

- [README](../README.md)
- [工作流程详解](WORKFLOW.md)
- [SKILL.md](../SKILL.md)
- [GitHub Issues](https://github.com/wei-ze-guang/zlibrary-to-notebooklm/issues)

---

## 💡 最佳实践

1. 定期检查登录状态：

   ```bash
   ls -lh ~/.zlibrary/storage_state.json
   ```

2. 先搜索再上传：

   ```bash
   python3 scripts/search.py "书名 作者" --limit 20
   ```

3. 批量处理时添加延迟：

   ```bash
   for url in "url1" "url2" "url3"; do
       python3 scripts/upload.py "$url"
       sleep 5
   done
   ```

4. 只处理你有合法访问权限的内容。

---

**文档版本**: 1.0.0

**最后更新**: 2026-07-07
