# Local Assets Resumable Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make downloaded files durable first-class assets in the Web/VSCode workbench, so upload failures can be inspected and retried without downloading again.

**Architecture:** Keep `scripts/upload.py` as the file conversion/upload implementation. Add disk-backed task manifests under `/tmp/zlibrary-to-notebooklm/tasks/<task-id>/manifest.json`, expose local assets via `scripts/web_api.py`, and teach the React workbench to list those assets and start upload-only tasks from local files.

**Tech Stack:** Python `ThreadingHTTPServer`, Python `unittest`, React/Vite/TypeScript, existing NotebookLM CLI integration.

## Global Constraints

- Do not install packages or system tools.
- Only allow local upload paths under the existing task workspace root.
- Preserve the existing `/api/upload` full download+upload workflow.
- Use TDD for backend helpers and API behavior.
- Keep the UI compact and avoid outer-page scrolling regressions.

---

### Task 1: Persist Task Manifests and Local Asset Metadata

**Files:**
- Modify: `scripts/web_api.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `WORKSPACE_ROOT: Path`
- Produces: `task_manifest_path(task_id: str) -> Path`
- Produces: `save_task_manifest(task: UploadTask) -> None`
- Produces: `scan_local_assets(workspace_root: Path = WORKSPACE_ROOT) -> list[dict[str, Any]]`
- Extends: `UploadTask` with `mode`, `local_path`, `downloaded_file`, `final_file`, `file_format`, `stage`

- [ ] Write tests that create a fake task workspace with `manifest.json` and downloaded files, then assert `scan_local_assets()` returns filename, path, size, extension, status, error, notebook id, and upload result.
- [ ] Run `python3 -m unittest tests.test_web_api.WebApiTest.test_scan_local_assets_reads_manifest -v` and confirm RED.
- [ ] Implement manifest helpers and local asset scanning with path safety.
- [ ] Run the targeted test and confirm GREEN.

### Task 2: Split Download+Upload from Local Upload

**Files:**
- Modify: `scripts/web_api.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `create_local_upload_task(local_path: str, notebook_id: str | None, notebook_title: str | None) -> UploadTask`
- Produces: `run_local_upload_task(task: UploadTask) -> None`
- Produces: `resolve_safe_local_file(path_value: str, workspace_root: Path = WORKSPACE_ROOT) -> Path`
- Adds API: `GET /api/local-files`
- Adds API: `POST /api/upload-local`

- [ ] Write tests for `resolve_safe_local_file()` accepting workspace files and rejecting `/etc/passwd` or sibling paths.
- [ ] Write tests for `create_local_upload_task()` preserving the selected local path and mode.
- [ ] Write tests for `GET /api/local-files` through helper coverage if full handler testing is too heavy.
- [ ] Run targeted tests and confirm RED.
- [ ] Implement local upload task creation, upload-only runner, and API routes.
- [ ] Run targeted tests and confirm GREEN.

### Task 3: Record Detailed Failure and Success State

**Files:**
- Modify: `scripts/web_api.py`
- Modify: `scripts/upload.py`
- Modify: `tests/test_web_api.py`
- Modify: `tests/test_upload_notebook_target.py`

**Interfaces:**
- Produces manifest fields: `stage`, `downloaded_file`, `final_file`, `file_format`, `error`, `result`, `updated_at`
- Improves upload failures to include `stderr` or parse failure detail already returned by `upload_to_notebooklm()`.

- [ ] Write tests that a failed upload leaves `downloaded_file` and `final_file` in serialized task/manifest.
- [ ] Write tests that successful local upload records `result` and status.
- [ ] Run tests and confirm RED.
- [ ] Update `run_upload_task()` and `run_local_upload_task()` to save manifest after each meaningful stage.
- [ ] Run tests and confirm GREEN.

### Task 4: Add Web Local Assets Panel and Retry Actions

**Files:**
- Modify: `web/src/main.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `GET /api/local-files`
- Consumes: `POST /api/upload-local` with `{ "local_path": "...", "notebook_id": "...", "notebook_title": "..." }`

- [ ] Add TypeScript type `LocalAsset`.
- [ ] Add state and loader for local assets.
- [ ] Add a compact local assets section in Step 2 or Step 3 showing filename, status, size, type, updated time, and error.
- [ ] Add an “上传本地文件/重试上传” button that starts `/api/upload-local`.
- [ ] Show `task.error` as a clear failure callout above logs.
- [ ] Run `pnpm build` in `web/` and confirm GREEN.

### Task 5: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/WORKFLOW.md`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] Document where downloads/manifests live.
- [ ] Document how failed uploads can be retried from local assets.
- [ ] Run:
  - `python3 -m unittest discover -v`
  - `python3 -m py_compile scripts/web_api.py scripts/search.py scripts/upload.py scripts/browser.py scripts/login.py scripts/convert_epub.py`
  - `PATH="/Users/macbook/.nvm/versions/node/v22.20.0/bin:$PATH" pnpm build` in `web/`
  - `PATH="/Users/macbook/.nvm/versions/node/v22.20.0/bin:$PATH" pnpm test` in `vscode-extension/`
  - `git diff --check`
