#!/usr/bin/env node
"use strict";

const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const EXTENSION_ROOT = path.resolve(__dirname, "..");

function parseArgs(argv) {
  const options = {
    codePath: "",
    dryRun: false,
    keepVsix: false,
    packageOnly: false,
    skipWebBuild: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--") {
      continue;
    } else if (arg === "--code") {
      options.codePath = argv[index + 1] || "";
      index += 1;
    } else if (arg.startsWith("--code=")) {
      options.codePath = arg.slice("--code=".length);
    } else if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (arg === "--keep-vsix") {
      options.keepVsix = true;
    } else if (arg === "--package-only") {
      options.packageOnly = true;
    } else if (arg === "--skip-web-build") {
      options.skipWebBuild = true;
    } else if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else {
      throw new Error(`未知参数: ${arg}`);
    }
  }

  return options;
}

function readPackageJson(extensionRoot = EXTENSION_ROOT) {
  return JSON.parse(fs.readFileSync(path.join(extensionRoot, "package.json"), "utf8"));
}

function run(command, args, options = {}) {
  const result = childProcess.spawnSync(command, args, {
    cwd: options.cwd || EXTENSION_ROOT,
    env: options.env || process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const detail = result.stderr || result.stdout || "";
    throw new Error(`${command} ${args.join(" ")} 执行失败${detail ? `\n${detail.trim()}` : ""}`);
  }
  return result;
}

function commandOutput(command, args) {
  return run(command, args, { capture: true }).stdout.trim();
}

function executableExists(filePath) {
  try {
    return Boolean(filePath && fs.existsSync(filePath));
  } catch {
    return false;
  }
}

function pathCommand(command, env = process.env) {
  const searchPath = String(env.PATH || "");
  const names = process.platform === "win32" ? [`${command}.cmd`, `${command}.exe`, command] : [command];
  for (const dir of searchPath.split(path.delimiter)) {
    for (const name of names) {
      const candidate = path.join(dir, name);
      if (executableExists(candidate)) {
        return candidate;
      }
    }
  }
  return "";
}

function vscodeCliCandidates(options = {}, env = process.env) {
  const candidates = [];
  if (options.codePath) candidates.push(options.codePath);
  if (env.VSCODE_CLI) candidates.push(env.VSCODE_CLI);

  if (process.platform === "darwin") {
    candidates.push("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code");
  }

  const fromPath = pathCommand("code", env);
  if (fromPath) candidates.push(fromPath);

  return Array.from(new Set(candidates.filter(Boolean)));
}

function classifyCliPath(candidate) {
  const resolved = executableExists(candidate) ? fs.realpathSync(candidate) : candidate;
  const normalized = resolved.toLowerCase();
  if (normalized.includes("cursor.app") || normalized.includes(`${path.sep}cursor`)) {
    return { ok: false, resolved, reason: "检测到 Cursor CLI，不会把 VSCode 插件安装到 Cursor" };
  }
  if (normalized.includes("vscodium") || normalized.includes("codium")) {
    return { ok: false, resolved, reason: "检测到 VSCodium/Codium CLI，不会误装到非官方 VSCode" };
  }
  if (normalized.includes("visual studio code.app") || path.basename(candidate).toLowerCase() === "code") {
    return { ok: true, resolved };
  }
  return { ok: false, resolved, reason: "无法确认这是官方 VSCode CLI" };
}

function selectVsCodeCli(options = {}, env = process.env) {
  const rejected = [];
  for (const candidate of vscodeCliCandidates(options, env)) {
    if (candidate !== "code" && !executableExists(candidate)) {
      rejected.push(`${candidate}: 不存在`);
      continue;
    }
    const classified = classifyCliPath(candidate);
    if (!classified.ok) {
      rejected.push(`${candidate}: ${classified.reason}`);
      continue;
    }
    try {
      commandOutput(candidate, ["--version"]);
      return { command: candidate, resolved: classified.resolved };
    } catch (error) {
      rejected.push(`${candidate}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  throw new Error([
    "没有找到可用的官方 VSCode CLI。",
    "请在 VSCode 中执行 Shell Command: Install 'code' command in PATH，",
    "或使用 --code 指定: /Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
    rejected.length ? `已拒绝/失败的候选:\n- ${rejected.join("\n- ")}` : "",
  ].filter(Boolean).join("\n"));
}

function findVsce(extensionRoot = EXTENSION_ROOT) {
  const binary = process.platform === "win32" ? "vsce.cmd" : "vsce";
  const localVsce = path.join(extensionRoot, "node_modules", ".bin", binary);
  if (executableExists(localVsce)) {
    return localVsce;
  }
  throw new Error("缺少本地 @vscode/vsce。请先在 vscode-extension 目录运行 pnpm install。");
}

function findPnpm(repoRoot, env = process.env) {
  const localPnpm = pathCommand("pnpm", env);
  if (localPnpm) {
    return localPnpm;
  }
  const knownPnpm = path.join(process.env.HOME || "", ".nvm", "versions", "node", "v22.20.0", "bin", process.platform === "win32" ? "pnpm.cmd" : "pnpm");
  if (executableExists(knownPnpm)) {
    return knownPnpm;
  }
  throw new Error(`找不到 pnpm，无法构建 Web 前端。请先确认 pnpm 在 PATH 中，或使用 --skip-web-build 跳过。仓库: ${repoRoot}`);
}

function buildWebDist(extensionRoot = EXTENSION_ROOT, env = process.env, options = {}) {
  const repoRoot = path.dirname(extensionRoot);
  const webRoot = path.join(repoRoot, "web");
  const packageJson = path.join(webRoot, "package.json");
  if (!executableExists(packageJson)) {
    throw new Error(`找不到 Web 项目: ${packageJson}`);
  }
  const pnpm = findPnpm(repoRoot, env);
  if (options.dryRun) {
    console.log(`[dry-run] 将构建 Web 前端: ${pnpm} build (cwd=${webRoot})`);
    return;
  }
  console.log("正在构建 Web 前端，确保插件使用最新 web/dist...");
  run(pnpm, ["build"], { cwd: webRoot, env });
}

function copyDirectory(source, target) {
  fs.cpSync(source, target, {
    recursive: true,
    filter: (entry) => {
      const name = path.basename(entry);
      return name !== "__pycache__" && !name.endsWith(".pyc") && name !== ".DS_Store";
    },
  });
}

function stageRuntimeAssets(extensionRoot = EXTENSION_ROOT, options = {}) {
  const repoRoot = path.dirname(extensionRoot);
  const bundledRoot = path.join(extensionRoot, "bundled");
  const sourceScripts = path.join(repoRoot, "scripts");
  const sourceWebDist = path.join(repoRoot, "web", "dist");
  const sourceRequirements = path.join(repoRoot, "requirements.txt");

  for (const requiredPath of [sourceScripts, sourceWebDist, sourceRequirements]) {
    if (!executableExists(requiredPath)) {
      throw new Error(`无法打包插件运行时，缺少: ${requiredPath}`);
    }
  }

  if (options.dryRun) {
    console.log(`[dry-run] 将同步运行时: ${sourceScripts} -> ${path.join(bundledRoot, "scripts")}`);
    console.log(`[dry-run] 将同步前端: ${sourceWebDist} -> ${path.join(bundledRoot, "web", "dist")}`);
    return;
  }

  fs.rmSync(bundledRoot, { recursive: true, force: true });
  fs.mkdirSync(path.join(bundledRoot, "web"), { recursive: true });
  copyDirectory(sourceScripts, path.join(bundledRoot, "scripts"));
  copyDirectory(sourceWebDist, path.join(bundledRoot, "web", "dist"));
  fs.copyFileSync(sourceRequirements, path.join(bundledRoot, "requirements.txt"));
  console.log(`已同步插件运行时: ${bundledRoot}`);
}

function removeOldVsix(extensionRoot, packageInfo) {
  const prefix = `${packageInfo.name}-`;
  const removed = [];
  for (const entry of fs.readdirSync(extensionRoot)) {
    if (entry.startsWith(prefix) && entry.endsWith(".vsix")) {
      fs.rmSync(path.join(extensionRoot, entry), { force: true });
      removed.push(entry);
    }
  }
  return removed;
}

function buildVsixName(packageInfo) {
  return `${packageInfo.name}-${packageInfo.version}.vsix`;
}

function printHelp() {
  console.log(`用法:
  pnpm install:local [-- --code <path>] [-- --keep-vsix] [-- --dry-run]
  pnpm package

选项:
  --code <path>    显式指定官方 VSCode code CLI
  --keep-vsix      不清理旧 VSIX
  --package-only   只打包，不安装
  --skip-web-build 跳过 web/dist 构建
  --dry-run        只显示将执行的动作
`);
}

function main(argv = process.argv.slice(2), env = process.env) {
  const options = parseArgs(argv);
  if (options.help) {
    printHelp();
    return;
  }

  const packageInfo = readPackageJson(EXTENSION_ROOT);
  const vsixName = buildVsixName(packageInfo);
  const vsixPath = path.join(EXTENSION_ROOT, vsixName);
  const vsce = findVsce(EXTENSION_ROOT);
  const vscodeCli = options.packageOnly ? null : selectVsCodeCli(options, env);

  console.log(`插件: ${packageInfo.displayName || packageInfo.name} ${packageInfo.version}`);
  console.log(`打包工具: ${vsce}`);
  if (vscodeCli) console.log(`VSCode CLI: ${vscodeCli.command}${vscodeCli.resolved ? ` -> ${vscodeCli.resolved}` : ""}`);

  if (!options.skipWebBuild) {
    buildWebDist(EXTENSION_ROOT, env, { dryRun: options.dryRun });
  } else {
    console.log("已跳过 Web 前端构建。");
  }
  stageRuntimeAssets(EXTENSION_ROOT, { dryRun: options.dryRun });

  if (options.dryRun) {
    console.log(`[dry-run] 将生成 ${vsixPath}`);
    if (vscodeCli) console.log(`[dry-run] 将执行覆盖安装: ${vscodeCli.command} --install-extension ${vsixPath} --force`);
    return;
  }

  if (!options.keepVsix) {
    const removed = removeOldVsix(EXTENSION_ROOT, packageInfo);
    if (removed.length) console.log(`已清理旧 VSIX: ${removed.join(", ")}`);
  }

  run(vsce, ["package", "--out", vsixPath], { cwd: EXTENSION_ROOT });
  console.log(`已打包: ${vsixPath}`);

  if (vscodeCli) {
    run(vscodeCli.command, ["--install-extension", vsixPath, "--force"], { cwd: EXTENSION_ROOT });
    console.log("已覆盖安装到本地 VSCode。请在 VSCode 中运行 Developer: Reload Window 重新加载插件。");
  }
}

if (require.main === module) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
  }
}

module.exports = {
  buildVsixName,
  buildWebDist,
  classifyCliPath,
  findPnpm,
  parseArgs,
  removeOldVsix,
  selectVsCodeCli,
  stageRuntimeAssets,
  vscodeCliCandidates,
};
