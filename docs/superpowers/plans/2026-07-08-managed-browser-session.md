# Managed Browser Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Z-Library automation browser reusable while making state, cleanup, VSCode shutdown, idle timeout, and crash recovery reliable.

**Architecture:** Add a backend `ManagedBrowserSession` that owns one Playwright persistent context and exposes status/start/close/restart APIs. Web API search/download uses managed pages while CLI scripts keep their current one-shot browser behavior. The React workbench adds a compact browser control strip; the VSCode extension asks the backend to close browser resources before killing the backend.

**Tech Stack:** Python `unittest`, Playwright async/sync APIs, React/TypeScript, VSCode extension Node tests.

## Global Constraints

- Do not install dependencies or system tools.
- Preserve CLI one-shot search/download behavior.
- Do not leave browser contexts open after explicit close or VSCode shutdown.
- Avoid duplicate browser launches with a manager-level lock.
- Do not close the managed browser while an active browser task is running unless force is requested.

---

### Task 1: Backend Browser Manager

**Files:**
- Modify: `scripts/web_api.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- `get_browser_status() -> dict`
- `start_managed_browser(headless: bool = True, keep_open: bool = True) -> dict`
- `close_managed_browser(force: bool = False) -> dict`
- `restart_managed_browser() -> dict`
- `GET /api/browser/status`
- `POST /api/browser/start`
- `POST /api/browser/close`
- `POST /api/browser/restart`

- [ ] Write failing tests for status, duplicate start, busy close rejection, force close, idle timeout, and restart.
- [ ] Implement manager state, locking, context start/close, active operation accounting, and HTTP endpoints.
- [ ] Verify backend tests pass.

### Task 2: Search/Download Reuse

**Files:**
- Modify: `scripts/search.py`
- Modify: `scripts/upload.py`
- Modify: `scripts/web_api.py`
- Modify: `tests/test_search_cli.py`
- Modify: `tests/test_upload_cli.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- `search_zlibrary_with_page(page, query, limit, base_url)`
- `ZLibraryAutoUploader.download_from_zlibrary_with_page(page, url)`

- [ ] Extract page-level search and download logic.
- [ ] Keep CLI one-shot behavior closing its own browser.
- [ ] Route Web API search/download through managed browser pages.

### Task 3: Frontend and VSCode UX

**Files:**
- Modify: `web/src/main.tsx`
- Modify: `web/src/styles.css`
- Modify: `vscode-extension/src/backend.js`
- Modify: `vscode-extension/src/extension.js`
- Modify: `vscode-extension/test/backend.test.js`

**Interfaces:**
- `closeBackendGracefully(url, timeoutMs)`
- Browser strip shows status and start/close/restart controls.

- [ ] Add browser status polling and action buttons.
- [ ] Add VSCode graceful backend stop: call `/api/browser/close` before killing the process.
- [ ] Document lifecycle and timeout behavior.
