# 📚 Z-Library 到 NotebookLM 自动化工具

[English](README.md) | [简体中文](README.zh-CN.md)

> 一键将 Z-Library 书籍自动下载并上传到 Google NotebookLM

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Claude Skill](https://img.shields.io/badge/Claude-Skill-success.svg)](https://claude.ai/claude-code)

---

## ⚠️ 重要免责声明

**本项目仅供学习、研究和技术演示用途。请严格遵守当地法律法规及版权规定，仅用于：**

- ✅ 你拥有合法访问权限的资源
- ✅ 公共领域或开源许可的文档（如 arXiv、Project Gutenberg）
- ✅ 个人拥有版权或已获授权的内容

**作者不鼓励、不支持任何形式的版权侵权行为，不承担任何法律责任。使用风险自负。**

**请尊重知识产权，支持正版阅读！**

---

## ✨ 特性

- 🔐 **一次登录，永久使用** - 类似 `notebooklm login` 的体验
- 🔎 **先搜索再处理** - 通过 CLI 搜索 Z-Library，复制准确书籍链接
- 📥 **智能下载** - 优先 PDF（保留排版），自动降级 EPUB → Markdown
- 📦 **智能分块** - 大文件自动分割（>350k 词），确保 CLI 上传成功
- 🤖 **全自动化** - 一条命令完成整个流程
- 🖥️ **可视化工作台** - 本地 React/Vite 页面支持搜索、选择知识库和上传
- 🎯 **格式自适应** - 自动检测并处理多种格式（PDF、EPUB、MOBI 等）
- 📊 **进度可视化** - 实时显示下载和转换进度

## 🎯 作为 Claude Skill 使用（推荐）

### 安装

```bash
# 1. 进入 Claude Skills 目录
cd ~/.claude/skills  # Windows: %APPDATA%\Claude\skills

# 2. 克隆仓库
git clone https://github.com/wei-ze-guang/zlibrary-to-notebooklm.git

# 3. 完成首次登录
cd zlibrary-to-notebooklm
notebooklm login
python3 scripts/login.py
```

### 使用方式

安装后，在 Claude Code 中直接说：

```text
用 zlibrary-to-notebooklm skill 处理这个 Z-Library 链接：
https://zh.zlib.li/book/25314781/aa05a1/书的标题
```

Claude 会自动：

- 下载书籍（优先 PDF）
- 创建 NotebookLM 笔记本
- 上传文件
- 返回笔记本 ID
- 建议后续问题

---

## 🛠️ 传统方式安装

### 1. 安装依赖

```bash
# 克隆仓库
git clone https://github.com/wei-ze-guang/zlibrary-to-notebooklm.git
cd zlibrary-to-notebooklm

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium
```

可视化工作台是可选功能。前端使用 Vite 7，因此需要 Node.js `^20.19.0` 或 `>=22.12.0`，以及 `pnpm`。

### 2. 登录 NotebookLM CLI（仅需一次）

```bash
# 确认 notebooklm 命令可用
notebooklm --version

# 打开授权流程，按提示登录 Google 账号
notebooklm login
```

如果 `notebooklm login` 不可用，请先运行 `notebooklm --help` 查看当前版本提供的登录/授权命令。

### 3. 登录 Z-Library（仅需一次）

```bash
python3 scripts/login.py
```

**操作步骤：**

1. 浏览器会自动打开并访问 Z-Library
2. 在浏览器中完成登录
3. 登录成功后，回到终端按 **ENTER**
4. 会话状态已保存！

### 4. 搜索书籍（可选）

```bash
python3 scripts/search.py "机器学习"
```

脚本会展示搜索结果编号、书名、简要信息和 Z-Library 链接。复制想要处理的链接后，再运行上传命令。

### 5. 下载并上传书籍

```bash
python3 scripts/upload.py "https://zh.zlib.li/book/..."
```

**自动完成：**

- ✅ 使用已保存的会话登录
- ✅ 优先下载 PDF（保留排版）
- ✅ 自动降级 EPUB → Markdown
- ✅ 智能分块大文件（>350k 词）
- ✅ 创建 NotebookLM 笔记本
- ✅ 上传内容
- ✅ 返回笔记本 ID

## 📖 使用示例

### 基本用法

```bash
# 搜索书籍
python3 scripts/search.py "机器学习"

# 下载单本书籍
python3 scripts/upload.py "https://zh.zlib.li/book/12345/..."
```

### 可视化工作台

```bash
# 首次进入前端目录安装依赖并构建
cd web
pnpm install
pnpm build
cd ..

# 启动本地页面
python3 scripts/web_api.py
```

打开 `http://127.0.0.1:7860`，即可在页面中搜索书籍、选择已有 NotebookLM 知识库、创建新知识库，并一键上传。

### 批量处理

```bash
# 批量下载多本书
for url in "url1" "url2" "url3"; do
    python3 scripts/upload.py "$url"
done
```

### 使用 NotebookLM

```bash
# 上传完成后，使用笔记本
notebooklm use <返回的笔记本ID>

# 开始提问
notebooklm ask "这本书的核心观点是什么？"
notebooklm ask "总结第3章的内容"
```

## 🔄 工作流程

```text
Z-Library URL
    ↓
1. 启动浏览器（使用已保存的会话）
    ↓
2. 访问书籍页面
    ↓
3. 智能选择格式：
   - 优先 PDF（保留排版）
   - 备选 EPUB（转换为 Markdown）
   - 其他格式（自动转换）
    ↓
4. 下载文件到 ~/Downloads
    ↓
5. 格式处理：
   - PDF → 直接使用
   - EPUB → 转换为 Markdown
   - 检查文件大小 → 超过 350k 词自动分块
    ↓
6. 创建 NotebookLM 笔记本
    ↓
7. 上传内容（分块文件会逐个上传）
    ↓
8. 返回笔记本 ID ✅
```

## 📁 项目结构

```text
zlibrary-to-notebooklm/
├── SKILL.md              # Skill 核心定义（必需）
├── README.md             # 英文项目文档
├── README.zh-CN.md       # 中文项目文档
├── LICENSE               # MIT 许可证
├── package.json          # npm 配置（用于 Claude Code skill）
├── skill.yaml            # Skill 定义
├── requirements.txt      # Python 依赖
├── scripts/              # 可执行脚本（官方标准）
│   ├── login.py         # 登录脚本
│   ├── search.py        # 搜索结果展示脚本
│   ├── upload.py        # 下载+上传脚本
│   ├── web_api.py       # 本地 Web 工作台 API
│   └── convert_epub.py  # EPUB 转换工具
├── web/                  # React/Vite 可视化工作台
│   ├── package.json      # 前端脚本和依赖
│   ├── src/main.tsx      # 工作台 UI 入口
│   ├── src/styles.css    # 工作台样式
│   └── tsconfig*.json    # TypeScript 配置
├── tests/                # Python unittest 测试
├── docs/                 # 文档
│   ├── WORKFLOW.md      # 工作流程详解
│   └── TROUBLESHOOTING.md # 故障排除
└── INSTALL.md            # 安装指南
```

## 🔧 配置文件

所有配置保存在 `~/.zlibrary/` 目录：

```text
~/.zlibrary/
├── storage_state.json    # 登录会话（cookies）
├── browser_profile/      # 浏览器数据
└── config.json          # 账号配置（备用）
```

## 🛠️ 依赖项

- **Python 3.8+**
- **playwright** - 浏览器自动化
- **ebooklib** - EPUB 文件处理
- **beautifulsoup4 + lxml** - 搜索结果和 EPUB 内容的 HTML 解析
- **NotebookLM CLI** - Google NotebookLM 命令行工具
- **Node.js + pnpm** - 可选，仅构建可视化工作台时需要

## 📝 命令参考

### 登录 NotebookLM

```bash
notebooklm login
```

### 登录 Z-Library

```bash
python3 scripts/login.py
```

### 上传

```bash
python3 scripts/upload.py <Z-Library URL>
```

### 搜索

```bash
python3 scripts/search.py <搜索关键词>
python3 scripts/search.py <搜索关键词> --limit 20
```

### Web 工作台

```bash
python3 scripts/web_api.py
```

本地工作台提供的 API：

- `GET /api/search?q=<关键词>&limit=12`
- `GET /api/notebooks`
- `POST /api/notebooks`，请求体为 `{"title":"知识库名称"}`
- `POST /api/upload`，请求体为 `{"zlibrary_url":"...","notebook_id":"..."}` 或 `{"zlibrary_url":"...","notebook_title":"..."}`
- `GET /api/tasks/<task_id>`

### npm 脚本快捷方式

```bash
npm run login
npm run search -- "机器学习"
npm run upload -- "https://zh.zlib.li/book/..."
npm run web
```

### 查看会话状态

```bash
ls -lh ~/.zlibrary/storage_state.json
```

### 重新登录

```bash
rm ~/.zlibrary/storage_state.json
python3 scripts/login.py
```

## ✅ 开发验证

```bash
python3 -m unittest discover -v
```

如果修改了前端：

```bash
cd web
pnpm build
```

## 📊 NotebookLM 限制说明

本项目已针对 NotebookLM 的实际限制进行优化：

### 官方限制
- **单文件大小**: 200MB
- **每来源词数**: 500,000 词

### 实际使用建议（CLI 工具）
- **安全词数**: 每个文件不超过 350,000-380,000 词
- **原因**: NotebookLM CLI 工具对大文件处理存在超时和 API 限制

### 本项目的解决方案
✅ **自动文件分块**：
- 当 EPUB 转换为 Markdown 后，脚本会自动检测词数
- 超过 350,000 词的文件会自动分割成多个小文件
- 每个分块会单独上传到同一个 NotebookLM 笔记本
- 按章节智能分割，保持内容完整性

**示例**：
```bash
📊 词数统计: 2,700,000
⚠️  文件超过 350k 词（NotebookLM CLI 限制）
📊 文件过大，开始分割...
   总词数: 2,700,000
   每块最大: 350,000 词
   ✅ Part 1/8: 342,000 词
   ✅ Part 2/8: 338,000 词
   ...
📦 检测到 8 个文件分块
```

### 为什么选择 350k 词作为阈值？
- 官方限制是 500k 词，但 CLI 工具在接近此限制时容易超时
- 350k 词是经过测试的安全值，可确保稳定上传
- 本地 Web 工作台同样使用 CLI 后端，因此遵循同一套分块策略

## 📚 更多文档

- [安装指南](INSTALL.md)
- [工作流程详解](docs/WORKFLOW.md)
- [故障排除指南](docs/TROUBLESHOOTING.md)

## 🤝 贡献

欢迎贡献！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [Z-Library](https://zh.zlib.li/) - 世界上最大的数字图书馆
- [Google NotebookLM](https://notebooklm.google.com/) - AI 驱动的笔记工具
- [Playwright](https://playwright.dev/) - 强大的浏览器自动化工具

## 📮 联系方式

- GitHub Issues: [提交问题](https://github.com/wei-ze-guang/zlibrary-to-notebooklm/issues)
- 讨论区: [GitHub Discussions](https://github.com/wei-ze-guang/zlibrary-to-notebooklm/discussions)

---

**⭐ 如果这个项目对你有帮助，请给个 Star！**
