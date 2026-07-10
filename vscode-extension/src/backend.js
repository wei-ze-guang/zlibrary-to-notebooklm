const http = require("node:http");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");

const DEFAULT_HOST = "127.0.0.1";

function getProjectRoot(extensionPath) {
  const bundledRoot = path.join(extensionPath, "bundled");
  if (fs.existsSync(path.join(bundledRoot, "scripts", "web_api.py"))) {
    return bundledRoot;
  }
  return path.basename(extensionPath) === "vscode-extension"
    ? path.dirname(extensionPath)
    : extensionPath;
}

function getHomeDir(env = process.env) {
  return env.HOME || os.homedir();
}

function getPyenvRoot(env = process.env) {
  if (env.PYENV_ROOT) {
    return env.PYENV_ROOT;
  }
  const home = getHomeDir(env);
  return home ? path.join(home, ".pyenv") : "";
}

function getExecutableIfPresent(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return "";
  }
  return filePath;
}

function prependPathEntries(env, entries) {
  const existing = String(env.PATH || "");
  const seen = new Set();
  const parts = [];
  for (const entry of [...entries, ...existing.split(path.delimiter)]) {
    if (!entry || seen.has(entry)) {
      continue;
    }
    seen.add(entry);
    parts.push(entry);
  }
  return parts.join(path.delimiter);
}

function selectPythonCommand(configuredPythonPath, env = process.env) {
  const configured = String(configuredPythonPath || "").trim();
  if (configured) {
    return configured;
  }
  if (env.PYTHON) {
    return env.PYTHON;
  }

  const pyenvPython = getExecutableIfPresent(path.join(getPyenvRoot(env), "shims", "python3"));
  return pyenvPython || "python3";
}

function buildBackendEnv(env = process.env) {
  const pyenvRoot = getPyenvRoot(env);
  const nextEnv = { ...env };
  const pyenvEntries = [
    path.join(pyenvRoot, "shims"),
    path.join(pyenvRoot, "bin"),
  ].filter((entry) => entry && fs.existsSync(entry));

  if (pyenvRoot && fs.existsSync(pyenvRoot)) {
    nextEnv.PYENV_ROOT = pyenvRoot;
  }
  nextEnv.PATH = prependPathEntries(env, pyenvEntries);
  return nextEnv;
}

function buildBackendArgs(projectRoot, host, port) {
  return [
    path.join(projectRoot, "scripts", "web_api.py"),
    "--host",
    host,
    "--port",
    String(port),
  ];
}

function buildWorkbenchUrl(host, port) {
  return `http://${host}:${port}`;
}

function buildWorkbenchFrameUrl(url, workspaces = []) {
  const target = new URL("/", url);
  if (Array.isArray(workspaces) && workspaces.length) {
    target.searchParams.set("vscode", "1");
    target.searchParams.set("workspaces", JSON.stringify(workspaces));
  }
  return target.toString();
}

function allocatePort(host = DEFAULT_HOST) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      server.close(() => {
        if (!address || typeof address === "string") {
          reject(new Error("无法分配本地端口"));
          return;
        }
        resolve(address.port);
      });
    });
  });
}

function waitForHttp(url, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;

  return new Promise((resolve, reject) => {
    const check = () => {
      const request = http.get(url, (response) => {
        response.resume();
        resolve();
      });
      request.once("error", (error) => {
        if (Date.now() >= deadline) {
          reject(error);
          return;
        }
        setTimeout(check, 250);
      });
      request.setTimeout(1000, () => {
        request.destroy(new Error("等待后端响应超时"));
      });
    };

    check();
  });
}

function closeBackendGracefully(url, timeoutMs = 1500) {
  if (!url) {
    return Promise.resolve(false);
  }
  const target = new URL("/api/browser/close", url);
  const body = JSON.stringify({ force: true });

  return new Promise((resolve) => {
    const request = http.request(
      target,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (response) => {
        response.resume();
        response.on("end", () => resolve(true));
      },
    );
    request.once("error", () => resolve(false));
    request.setTimeout(timeoutMs, () => {
      request.destroy();
      resolve(false);
    });
    request.end(body);
  });
}

function createNonce() {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let text = "";
  for (let i = 0; i < 24; i += 1) {
    text += alphabet[Math.floor(Math.random() * alphabet.length)];
  }
  return text;
}

function renderWorkbenchHtml(url, nonce, workspaces = []) {
  const frameUrl = buildWorkbenchFrameUrl(url, workspaces);
  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'none'; frame-src ${url}; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';"
    />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Z-Library to NotebookLM</title>
    <style>
      html, body {
        width: 100%;
        height: 100%;
        margin: 0;
        overflow: hidden;
        background: #f4f7fb;
      }
      .toolbar {
        height: 38px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 0 10px;
        color: #111827;
        background: #ffffff;
        border-bottom: 1px solid #d8dee8;
        font: 12px system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .toolbar strong {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .actions {
        display: flex;
        gap: 6px;
      }
      button {
        min-height: 26px;
        padding: 0 9px;
        color: #ffffff;
        background: #0f766e;
        border: 0;
        border-radius: 6px;
        font: inherit;
        font-weight: 700;
        cursor: pointer;
      }
      button.secondary {
        color: #0f766e;
        background: #f0fdfa;
        border: 1px solid #99f6e4;
      }
      iframe {
        width: 100%;
        height: calc(100% - 38px);
        border: 0;
        display: block;
      }
    </style>
  </head>
  <body>
    <div class="toolbar">
      <strong>Z-Library to NotebookLM Workbench</strong>
      <div class="actions">
        <button class="secondary" id="reload">刷新</button>
        <button class="secondary" id="browser">浏览器打开</button>
        <button id="restart">重启后端</button>
      </div>
    </div>
    <iframe id="workbench" src="${frameUrl}" title="Z-Library to NotebookLM Workbench"></iframe>
    <script nonce="${nonce}">
      const vscode = acquireVsCodeApi();
      document.getElementById("reload").addEventListener("click", () => {
        document.getElementById("workbench").contentWindow.location.reload();
      });
      document.getElementById("browser").addEventListener("click", () => {
        vscode.postMessage({ type: "openExternal" });
      });
      document.getElementById("restart").addEventListener("click", () => {
        vscode.postMessage({ type: "restartBackend" });
      });
    </script>
  </body>
</html>`;
}

module.exports = {
  DEFAULT_HOST,
  allocatePort,
  buildBackendEnv,
  buildBackendArgs,
  buildWorkbenchFrameUrl,
  buildWorkbenchUrl,
  closeBackendGracefully,
  createNonce,
  getProjectRoot,
  renderWorkbenchHtml,
  selectPythonCommand,
  waitForHttp,
};
