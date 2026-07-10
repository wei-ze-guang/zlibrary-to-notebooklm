# Z-Library to NotebookLM VSCode Extension

This extension opens the existing Z-Library to NotebookLM workbench inside VSCode.

## What It Does

- Starts `scripts/web_api.py` automatically on a free localhost port.
- Opens a VSCode Webview with the current React/Vite workbench.
- Reuses the existing Z-Library login, NotebookLM CLI login, search, notebook selection, upload, conversion, chunking, and task log flows.
- Passes the current VSCode workspace into the workbench. Search results can use `下载到工作区` to save the original downloaded book into `<workspace>/zlibrary-downloads/` without splitting or uploading it.
- Stops the backend process when the extension is deactivated or when the stop command is run. Before killing the backend, it asks `/api/browser/close` to release the managed automation browser.

## Commands

- `Z-Library to NotebookLM: Open Workbench`
- `Z-Library to NotebookLM: Restart Backend`
- `Z-Library to NotebookLM: Stop Backend`

## Development Usage

1. Build the web UI:

   ```bash
   cd web
   pnpm build
   cd ..
   ```

2. Open the repository in VSCode.
3. Run or package the extension from `vscode-extension/`.
4. Execute `Z-Library to NotebookLM: Open Workbench` from the command palette.

If the extension uses the wrong Python, set `zlibraryToNotebooklm.pythonPath` to the Python executable that has this project's dependencies installed.

## Package And Install Locally

Install package dependencies once:

```bash
cd vscode-extension
pnpm install
```

Build a VSIX only:

```bash
pnpm package
```

Build the latest Web UI, copy the Python backend and `web/dist` into the VSIX runtime bundle, package the extension, and install into local VSCode, replacing any existing installation:

```bash
pnpm install:local
```

If you only changed the extension shell and want to skip rebuilding `web/dist`:

```bash
pnpm install:local -- --skip-web-build
```

Even when `--skip-web-build` is used, the installer still copies the current `scripts/`, `requirements.txt`, and existing `web/dist` into `vscode-extension/bundled/` before packaging. The installed extension starts `bundled/scripts/web_api.py`, so it does not depend on the original repository path after installation.

The install script uses `code --install-extension <vsix> --force`, so the existing local extension is overwritten by default. On macOS it prefers the official VSCode CLI at:

```text
/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code
```

It rejects Cursor and VSCodium/Codium CLIs to avoid installing into the wrong editor. If your VSCode CLI is somewhere else, pass it explicitly:

```bash
pnpm install:local -- --code "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
```

After installation, reload VSCode with `Developer: Reload Window`.

The PNG icon appears in the Extensions view. The extension also contributes a left Activity Bar entry named `NotebookLM`; click it and then click `打开工作台` to open the Webview. VSCode may cache extension icons, so if the icon does not refresh immediately, run `Developer: Reload Window` or fully quit and reopen VSCode.

## Workspace Downloads

When the workbench is opened from the VSCode extension and the current window has a workspace folder, the search panel shows a compact workspace selector. The `下载到工作区` action:

- uses the same Z-Library login and managed browser as the normal download flow
- downloads the original file only
- creates `<workspace>/zlibrary-downloads/` if it does not exist
- avoids overwriting existing files by adding a numeric suffix
- reports the saved file path in the task progress card and task result

Use the normal `下载` action when you want the file to appear in the workbench's local file list for later processing, splitting, or upload.

## Tests

```bash
cd vscode-extension
pnpm test
```
