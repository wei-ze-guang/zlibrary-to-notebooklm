const childProcess = require("node:child_process");
const vscode = require("vscode");

const {
  DEFAULT_HOST,
  allocatePort,
  buildBackendEnv,
  buildBackendArgs,
  buildWorkbenchUrl,
  closeBackendGracefully,
  createNonce,
  getProjectRoot,
  renderWorkbenchHtml,
  selectPythonCommand,
  waitForHttp,
} = require("./backend");

let backendProcess = null;
let backendUrl = "";
let outputChannel = null;
let workbenchPanel = null;

function getOutputChannel() {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel("Z-Library to NotebookLM");
  }
  return outputChannel;
}

async function stopBackend() {
  if (backendUrl) {
    await closeBackendGracefully(backendUrl, 1500);
  }
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill();
  }
  backendProcess = null;
  backendUrl = "";
}

async function startBackend(context, forceRestart = false) {
  if (forceRestart) {
    await stopBackend();
  }
  if (backendProcess && backendUrl && backendProcess.exitCode === null) {
    return backendUrl;
  }

  const channel = getOutputChannel();
  const projectRoot = getProjectRoot(context.extensionPath);
  const config = vscode.workspace.getConfiguration("zlibraryToNotebooklm");
  const backendEnv = buildBackendEnv(process.env);
  const pythonCommand = selectPythonCommand(config.get("pythonPath"), backendEnv);
  const port = await allocatePort(DEFAULT_HOST);
  const args = buildBackendArgs(projectRoot, DEFAULT_HOST, port);
  const url = buildWorkbenchUrl(DEFAULT_HOST, port);

  channel.appendLine(`启动后端: ${pythonCommand} ${args.join(" ")}`);
  backendProcess = childProcess.spawn(pythonCommand, args, {
    cwd: projectRoot,
    env: backendEnv,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const processHandle = backendProcess;
  backendUrl = url;

  processHandle.stdout.on("data", (chunk) => channel.append(chunk.toString()));
  processHandle.stderr.on("data", (chunk) => channel.append(chunk.toString()));
  processHandle.on("exit", (code, signal) => {
    channel.appendLine(`后端已退出: code=${code ?? "null"} signal=${signal ?? "null"}`);
    if (backendProcess === processHandle) {
      backendProcess = null;
      backendUrl = "";
    }
  });

  try {
    await waitForHttp(url);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await stopBackend();
    throw new Error(`后端启动失败: ${message}`);
  }

  return url;
}

async function renderWorkbench(context, forceRestart = false) {
  const url = await startBackend(context, forceRestart);
  if (!workbenchPanel) {
    workbenchPanel = vscode.window.createWebviewPanel(
      "zlibraryToNotebooklmWorkbench",
      "Z-Library to NotebookLM",
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      },
    );
    workbenchPanel.onDidDispose(() => {
      workbenchPanel = null;
    });
    workbenchPanel.webview.onDidReceiveMessage(async (message) => {
      if (message?.type === "openExternal") {
        await vscode.env.openExternal(vscode.Uri.parse(backendUrl));
      }
      if (message?.type === "restartBackend") {
        await renderWorkbench(context, true);
      }
    });
  } else {
    workbenchPanel.reveal(vscode.ViewColumn.One);
  }

  workbenchPanel.webview.html = renderWorkbenchHtml(url, createNonce());
}

async function openWorkbench(context) {
  try {
    await renderWorkbench(context);
  } catch (error) {
    getOutputChannel().show(true);
    const message = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(message);
  }
}

async function restartBackend(context) {
  try {
    await renderWorkbench(context, true);
    vscode.window.showInformationMessage("Z-Library to NotebookLM 后端已重启");
  } catch (error) {
    getOutputChannel().show(true);
    const message = error instanceof Error ? error.message : String(error);
    vscode.window.showErrorMessage(message);
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("zlibraryToNotebooklm.openWorkbench", () => openWorkbench(context)),
    vscode.commands.registerCommand("zlibraryToNotebooklm.restartBackend", () => restartBackend(context)),
    vscode.commands.registerCommand("zlibraryToNotebooklm.stopBackend", async () => {
      await stopBackend();
      vscode.window.showInformationMessage("Z-Library to NotebookLM 后端已停止");
    }),
  );
}

function deactivate() {
  return stopBackend();
}

module.exports = {
  activate,
  deactivate,
};
