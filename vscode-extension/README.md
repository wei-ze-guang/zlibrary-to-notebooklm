# Z-Library to NotebookLM VSCode Extension

This extension opens the existing Z-Library to NotebookLM workbench inside VSCode.

## What It Does

- Starts `scripts/web_api.py` automatically on a free localhost port.
- Opens a VSCode Webview with the current React/Vite workbench.
- Reuses the existing Z-Library login, NotebookLM CLI login, search, notebook selection, upload, conversion, chunking, and task log flows.
- Stops the backend process when the extension is deactivated or when the stop command is run.

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

## Tests

```bash
cd vscode-extension
pnpm test
```
