# Local Asset Detail Workflow Plan

## Goal

Make the workbench safer after download/upload failures: users can download a search result to local storage, inspect local files in a compact list, open a detail modal to see original/processed/part/upload state, split/process local files, upload/retry without downloading again, and understand failures.

## Steps

1. Add backend task metadata for local assets
   - Persist original file, processed file, parts and upload attempts in `manifest.json`.
   - Keep backward compatibility with old manifests that only contain `downloaded_file` and `final_file`.

2. Add backend actions
   - `POST /api/download` downloads a Z-Library result into the task workspace without uploading.
   - `POST /api/process-local` converts/splits an existing workspace file without uploading.
   - Improve `/api/upload-local` so upload results mark part status and retain failure reasons.

3. Improve Web UX
   - Search result rows expose “下载” and “下载并上传”.
   - Local file list stays compact and collapsed.
   - A modal shows file metadata, target notebook, parts, upload status, and retry/process actions.

4. Update docs and verify
   - Document new workflow and APIs.
   - Run Python tests, compile checks, web build, VSCode extension tests, and diff check.
