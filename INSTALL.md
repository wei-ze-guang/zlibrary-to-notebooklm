# 安装指南

## 系统要求

- Python 3.8 或更高版本
- macOS / Linux / Windows
- 可用的 `notebooklm` 命令行工具
- 网络连接
- 可选：Node.js `^20.19.0` 或 `>=22.12.0` 与 `pnpm`，仅构建 Web 工作台时需要

## 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/wei-ze-guang/zlibrary-to-notebooklm.git
cd zlibrary-to-notebooklm
```

### 2. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

依赖包括 Playwright、ebooklib、beautifulsoup4 和 lxml。

### 3. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 4. 准备 NotebookLM CLI

```bash
notebooklm --version
notebooklm login
```

如果 `notebooklm` 命令不存在，请先按你使用的 NotebookLM CLI 来源完成安装；如果 `notebooklm login` 不可用，请运行 `notebooklm --help`，使用当前版本显示的登录或授权命令。

### 5. 登录 Z-Library

```bash
python3 scripts/login.py
```

浏览器打开后完成登录，回到终端按 ENTER。会话会保存到 `~/.zlibrary/storage_state.json`。

### 6. 搜索并上传

```bash
python3 scripts/search.py "机器学习" --limit 20
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

也可以通过 npm 脚本调用：

```bash
npm run search -- "机器学习"
npm run upload -- "https://zh.zlib.li/book/..."
```

## 可选：启用 Web 工作台

```bash
cd web
pnpm install
pnpm build
cd ..
python3 scripts/web_api.py
```

打开 `http://127.0.0.1:7860` 后，可以搜索书籍、选择已有 NotebookLM 笔记本、创建新笔记本并上传。

## 验证安装

```bash
python3 scripts/login.py --help
python3 scripts/search.py --help
python3 scripts/upload.py --help
python3 -m unittest discover -v
```

如需验证前端构建：

```bash
cd web
pnpm build
```

## 故障排除

### Playwright 浏览器安装失败

```bash
playwright install --with-deps chromium
```

### NotebookLM CLI 未登录

```bash
notebooklm login
```

如果 Web 工作台提示未找到 `notebooklm` 命令，请先确认终端中 `notebooklm --version` 能正常输出。

### Z-Library 会话失效

```bash
rm ~/.zlibrary/storage_state.json
python3 scripts/login.py
```

### 权限问题

```bash
chmod +x scripts/*.py
```

## 下一步

- 阅读 [README.md](README.md) 或 [README.zh-CN.md](README.zh-CN.md)
- 查看 [工作流程详解](docs/WORKFLOW.md)
- 遇到问题时查看 [故障排除指南](docs/TROUBLESHOOTING.md)
