const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  buildVsixName,
  classifyCliPath,
  findPnpm,
  parseArgs,
  removeOldVsix,
  stageRuntimeAssets,
  vscodeCliCandidates,
} = require("../scripts/install-local");

test("parseArgs defaults to force install behavior unless package-only is requested", () => {
  const options = parseArgs(["--code", "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"]);

  assert.equal(options.packageOnly, false);
  assert.equal(options.keepVsix, false);
  assert.equal(options.skipWebBuild, false);
  assert.equal(options.codePath, "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code");
});

test("parseArgs accepts pnpm argument separator before script options", () => {
  const options = parseArgs(["--", "--code", "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"]);

  assert.equal(options.codePath, "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code");
});

test("parseArgs can skip web build when only reinstalling the extension shell", () => {
  const options = parseArgs(["--skip-web-build"]);

  assert.equal(options.skipWebBuild, true);
});

test("findPnpm uses PATH pnpm before known fallbacks", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-path-"));
  const pnpm = path.join(root, process.platform === "win32" ? "pnpm.cmd" : "pnpm");
  fs.writeFileSync(pnpm, "");

  assert.equal(findPnpm("/repo", { PATH: root }), pnpm);
});

test("stageRuntimeAssets copies backend scripts, requirements, and built web dist", () => {
  const repoRoot = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-repo-"));
  const extensionRoot = path.join(repoRoot, "vscode-extension");
  fs.mkdirSync(path.join(repoRoot, "scripts"), { recursive: true });
  fs.mkdirSync(path.join(repoRoot, "web", "dist"), { recursive: true });
  fs.mkdirSync(extensionRoot, { recursive: true });
  fs.writeFileSync(path.join(repoRoot, "scripts", "web_api.py"), "print('ok')\n");
  fs.writeFileSync(path.join(repoRoot, "scripts", "search.py"), "");
  fs.writeFileSync(path.join(repoRoot, "web", "dist", "index.html"), "<html></html>");
  fs.writeFileSync(path.join(repoRoot, "requirements.txt"), "playwright\n");

  stageRuntimeAssets(extensionRoot);

  assert.equal(fs.existsSync(path.join(extensionRoot, "bundled", "scripts", "web_api.py")), true);
  assert.equal(fs.existsSync(path.join(extensionRoot, "bundled", "web", "dist", "index.html")), true);
  assert.equal(fs.existsSync(path.join(extensionRoot, "bundled", "requirements.txt")), true);
});

test("vscodeCliCandidates prefers explicit CLI then official macOS VSCode before PATH code", () => {
  const candidates = vscodeCliCandidates(
    { codePath: "/custom/code" },
    { PATH: "/missing", VSCODE_CLI: "/env/code" },
  );

  assert.equal(candidates[0], "/custom/code");
  assert.equal(candidates[1], "/env/code");
  if (process.platform === "darwin") {
    assert.equal(candidates[2], "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code");
  }
});

test("classifyCliPath rejects Cursor and accepts official VSCode path", () => {
  const cursor = classifyCliPath("/Applications/Cursor.app/Contents/Resources/app/bin/code");
  const vscode = classifyCliPath("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code");

  assert.equal(cursor.ok, false);
  assert.match(cursor.reason, /Cursor/);
  assert.equal(vscode.ok, true);
});

test("removeOldVsix only removes package-matching VSIX files", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zlnm-vsix-"));
  fs.writeFileSync(path.join(root, "zlibrary-to-notebooklm-vscode-0.1.0.vsix"), "");
  fs.writeFileSync(path.join(root, "other-0.1.0.vsix"), "");
  fs.writeFileSync(path.join(root, "zlibrary-to-notebooklm-vscode.txt"), "");

  const removed = removeOldVsix(root, { name: "zlibrary-to-notebooklm-vscode" });

  assert.deepEqual(removed, ["zlibrary-to-notebooklm-vscode-0.1.0.vsix"]);
  assert.equal(fs.existsSync(path.join(root, "zlibrary-to-notebooklm-vscode-0.1.0.vsix")), false);
  assert.equal(fs.existsSync(path.join(root, "other-0.1.0.vsix")), true);
});

test("buildVsixName uses package name and version", () => {
  assert.equal(
    buildVsixName({ name: "zlibrary-to-notebooklm-vscode", version: "0.1.0" }),
    "zlibrary-to-notebooklm-vscode-0.1.0.vsix",
  );
});

test("package manifest contributes an activity bar entry and icon", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));

  assert.equal(manifest.icon, "media/icon.png");
  assert.equal(manifest.contributes.viewsContainers.activitybar[0].icon, "resources/activity-icon.svg");
  assert.equal(manifest.contributes.views.zlibraryToNotebooklm[0].id, "zlibraryToNotebooklm.openWorkbenchView");
});
