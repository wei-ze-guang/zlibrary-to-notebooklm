# VSCode Extension Replica Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a VSCode extension entrypoint that reproduces the current Z-Library to NotebookLM web workbench inside VSCode.

**Architecture:** The extension starts the existing Python `scripts/web_api.py` backend on a free localhost port, then opens a VSCode Webview that embeds that backend with an iframe. This reuses the current React/Vite UI, API routes, login flows, search metadata display, notebook selection, upload task logs, conversion, chunking, and NotebookLM CLI integration without duplicating business logic.

**Tech Stack:** VSCode Extension API, Node.js CommonJS, Python `ThreadingHTTPServer`, current React/Vite `web/dist`.

## Global Constraints

- Do not install new packages or global tooling.
- Keep the existing Python scripts as the source of truth for search, login, conversion, chunking, and upload.
- Add tests before implementation for new backend argument parsing and extension helper behavior.
- The extension must not require users to manually run `python3 scripts/web_api.py`.

---

### Task 1: Make Web API Bind Configurable

**Files:**
- Modify: `scripts/web_api.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `parse_server_args(argv: list[str] | None = None) -> argparse.Namespace`
- Produces: `run_server(host: str, port: int) -> None`

- [ ] Write failing tests for `--host` and `--port`.
- [ ] Implement `parse_server_args` and `run_server`.
- [ ] Keep the default behavior at `127.0.0.1:7860`.

### Task 2: Add VSCode Extension Scaffold

**Files:**
- Create: `vscode-extension/package.json`
- Create: `vscode-extension/src/backend.js`
- Create: `vscode-extension/src/extension.js`
- Create: `vscode-extension/test/backend.test.js`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `allocatePort() -> Promise<number>`
- Produces: `buildBackendArgs(projectRoot: string, host: string, port: number) -> string[]`
- Produces: `renderWorkbenchHtml(url: string, nonce: string) -> string`

- [ ] Write failing Node tests for helper functions.
- [ ] Implement helper functions.
- [ ] Register VSCode commands to open, reload, restart, and stop the workbench.

### Task 3: Document Extension Usage

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/WORKFLOW.md`

- [ ] Add VSCode extension usage and development notes.
- [ ] Mention that the extension starts the backend automatically and reuses the existing Web UI.

### Task 4: Verify

**Commands:**
- `python3 -m unittest discover -v`
- `python3 -m py_compile scripts/web_api.py scripts/search.py scripts/upload.py scripts/browser.py scripts/login.py scripts/convert_epub.py`
- `PATH="/Users/macbook/.nvm/versions/node/v22.20.0/bin:$PATH" pnpm build` in `web/`
- `PATH="/Users/macbook/.nvm/versions/node/v22.20.0/bin:$PATH" pnpm test` in `vscode-extension/`
- `git diff --check`
