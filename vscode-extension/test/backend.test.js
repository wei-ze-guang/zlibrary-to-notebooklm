const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  buildBackendEnv,
  buildBackendArgs,
  buildWorkbenchUrl,
  closeBackendGracefully,
  getProjectRoot,
  renderWorkbenchHtml,
  selectPythonCommand,
} = require("../src/backend");

test("getProjectRoot resolves the repository root from the extension folder", () => {
  const extensionPath = path.join("/repo", "vscode-extension");

  assert.equal(getProjectRoot(extensionPath), "/repo");
});

test("buildBackendArgs points at web_api.py with host and port", () => {
  const args = buildBackendArgs("/repo", "127.0.0.1", 51234);

  assert.deepEqual(args, [
    path.join("/repo", "scripts", "web_api.py"),
    "--host",
    "127.0.0.1",
    "--port",
    "51234",
  ]);
});

test("buildWorkbenchUrl returns the local backend URL", () => {
  assert.equal(buildWorkbenchUrl("127.0.0.1", 51234), "http://127.0.0.1:51234");
});

test("selectPythonCommand prefers configured python path", () => {
  assert.equal(selectPythonCommand("/custom/python", {}), "/custom/python");
});

test("selectPythonCommand falls back to environment and python3", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-home-"));

  assert.equal(selectPythonCommand("", { PYTHON: "/env/python" }), "/env/python");
  assert.equal(selectPythonCommand("", { HOME: home }), "python3");
});

test("selectPythonCommand prefers a user pyenv python shim when VSCode has no shell PATH", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-home-"));
  const pythonShim = path.join(home, ".pyenv", "shims", "python3");
  fs.mkdirSync(path.dirname(pythonShim), { recursive: true });
  fs.writeFileSync(pythonShim, "#!/usr/bin/env bash\n");
  fs.chmodSync(pythonShim, 0o755);

  assert.equal(selectPythonCommand("", { HOME: home }), pythonShim);
});

test("buildBackendEnv exposes pyenv commands to the Python backend", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-home-"));
  const pyenvRoot = path.join(home, ".pyenv");
  fs.mkdirSync(path.join(pyenvRoot, "shims"), { recursive: true });
  fs.mkdirSync(path.join(pyenvRoot, "bin"), { recursive: true });

  const env = buildBackendEnv({ HOME: home, PATH: "/usr/bin" });
  const pathParts = env.PATH.split(path.delimiter);

  assert.equal(pathParts[0], path.join(pyenvRoot, "shims"));
  assert.equal(pathParts[1], path.join(pyenvRoot, "bin"));
  assert.equal(env.PYENV_ROOT, pyenvRoot);
});

test("renderWorkbenchHtml embeds the backend iframe and CSP", () => {
  const html = renderWorkbenchHtml("http://127.0.0.1:51234", "abc123");

  assert.match(html, /iframe/);
  assert.match(html, /src="http:\/\/127\.0\.0\.1:51234"/);
  assert.match(html, /frame-src http:\/\/127\.0\.0\.1:51234/);
  assert.match(html, /nonce-abc123/);
});

test("closeBackendGracefully posts browser close before resolving", async () => {
  const calls = [];
  const server = require("node:http").createServer((request, response) => {
    calls.push({ method: request.method, url: request.url });
    response.writeHead(200, { "content-type": "application/json" });
    response.end("{}");
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();

  try {
    await closeBackendGracefully(`http://127.0.0.1:${port}`, 1000);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }

  assert.deepEqual(calls, [{ method: "POST", url: "/api/browser/close" }]);
});
