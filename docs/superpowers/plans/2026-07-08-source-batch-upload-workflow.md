# Source Batch Upload Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local assets behave as selectable upload sources with reliable per-source status, notebook targeting, retry, processing strategy, and compact UI.

**Architecture:** Backend owns source selection, processing policy, task-level locking, and per-source upload records in `manifest.json`. Frontend renders the detail modal as the primary source manager: local notebook target, selectable source table, batch upload, failed retry, collapsed per-source records, and guarded reprocess actions.

**Tech Stack:** Python `unittest` backend API, React/TypeScript frontend, CSS, existing NotebookLM CLI and Playwright integration.

## Global Constraints

- Do not install packages or system tools.
- Do not revert unrelated dirty worktree changes.
- Uploading existing processed sources must not implicitly reconvert or resplit.
- Reprocessing an already processed asset must require an explicit strategy.
- Batch upload must support an arbitrary subset of source paths and record each source result.

---

### Task 1: Backend Source Workflow

**Files:**
- Modify: `tests/test_web_api.py`
- Modify: `scripts/web_api.py`

**Interfaces:**
- Produces: `create_sources_upload_task(source_paths, notebook_id, notebook_title, workspace_root, task_id)`
- Produces: `run_sources_upload_task(task)`
- Produces: `POST /api/upload-sources`
- Produces: `POST /api/process-local` with `strategy: "keep" | "replace" | "version"`

- [ ] Write failing tests for selected source batch upload, source upload records, upload-local using existing sources, and reprocess strategy guard.
- [ ] Run targeted tests and verify they fail for missing behavior.
- [ ] Implement source selection fields, task locks, existing-source upload resolution, batch source upload, per-source records, and process strategy validation.
- [ ] Run targeted tests and full backend tests.

### Task 2: Frontend Detail Modal

**Files:**
- Modify: `web/src/main.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- Consumes: `/api/upload-sources`
- Consumes: per-source `upload_records`
- Consumes: `/api/process-local` strategy body

- [ ] Add modal-local notebook selection initialized from global selection.
- [ ] Add source checkbox state, select all, failed-only, ready-only, upload selected, and retry failed.
- [ ] Replace always-expanded upload records with per-source collapsed history.
- [ ] Add guarded processing controls for keep, replace, and version strategies.
- [ ] Tighten visual hierarchy and inner scrolling without outer page scroll.

### Task 3: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/WORKFLOW.md`
- Modify: `docs/TROUBLESHOOTING.md`

- [ ] Document source selection upload, modal target selection, per-source records, failed retry, and processing strategies.
- [ ] Run Python tests, frontend build, extension tests, and diff checks.
