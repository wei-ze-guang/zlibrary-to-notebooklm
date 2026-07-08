import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Database,
  Download,
  Eye,
  PanelRightClose,
  PanelRightOpen,
  Loader2,
  LogIn,
  Plus,
  RefreshCcw,
  Scissors,
  Search,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import "./styles.css";

type SearchResult = {
  title: string;
  url: string;
  details: string;
  author?: string;
  publisher?: string;
  year?: string;
  extension?: string;
  filesize?: string;
  language?: string;
};

type Notebook = {
  id: string;
  title: string;
};

type UploadTask = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  zlibrary_url?: string;
  book_key?: string;
  stage?: string;
  progress?: TaskProgress;
  logs: string[];
  error?: string | null;
  result?: Record<string, unknown> | null;
};

type TaskProgress = {
  phase?: string;
  percent?: number;
  label?: string;
  detail?: string;
};

type LocalAsset = {
  task_id: string;
  filename: string;
  local_path: string;
  extension: string;
  size: number;
  mode?: string;
  status: string;
  stage?: string | null;
  error?: string | null;
  zlibrary_url?: string | null;
  book_key?: string | null;
  notebook_id?: string | null;
  notebook_title?: string | null;
  file_format?: string | null;
  result?: Record<string, unknown> | null;
  original_file?: LocalFileInfo | null;
  processed_file?: LocalFileInfo | null;
  parts?: LocalPart[];
  upload_sources?: UploadSource[];
  upload_summary?: UploadSummary;
  uploads?: LocalUpload[];
  downloaded_file?: string | null;
  final_file?: string | null;
  updated_at?: number;
  progress?: TaskProgress | null;
};

type LocalFileInfo = {
  path: string;
  filename: string;
  extension: string;
  size: number;
  mtime?: number | null;
};

type LocalPart = LocalFileInfo & {
  index?: number | null;
  status?: string | null;
  source_id?: string | null;
  error?: string | null;
};

type UploadSource = LocalFileInfo & {
  kind?: "file" | "part" | string;
  index?: number | null;
  total?: number | null;
  status?: string | null;
  source_id?: string | null;
  error?: string | null;
  upload_records?: SourceUploadRecord[];
  last_notebook_id?: string | null;
  last_notebook_title?: string | null;
  last_uploaded_at?: number | null;
};

type UploadSummary = {
  total: number;
  uploaded: number;
  failed: number;
  uploading: number;
  ready: number;
  state: string;
};

type LocalUpload = {
  scope?: string | null;
  status?: string | null;
  notebook_id?: string | null;
  notebook_title?: string | null;
  title?: string | null;
  source_id?: string | null;
  source_ids?: string[];
  source_records?: SourceUploadRecord[];
  chunks?: number | null;
  error?: string | null;
  updated_at?: number;
};

type SourceUploadRecord = {
  status?: string | null;
  notebook_id?: string | null;
  notebook_title?: string | null;
  title?: string | null;
  source_path?: string | null;
  source_filename?: string | null;
  source_id?: string | null;
  error?: string | null;
  updated_at?: number;
};

type AuthSession = {
  id: string;
  status: string;
  logs: string[];
  error?: string | null;
};

type AuthStatus = {
  zlibrary: {
    logged_in: boolean;
    status: string;
    message: string;
    storage_state: string;
    session?: AuthSession | null;
  };
  notebooklm: {
    installed: boolean;
    logged_in: boolean;
    status: string;
    message: string;
    notebooks_count?: number;
    login_process?: { status: string; returncode: number | null } | null;
  };
};

type BrowserStatus = {
  status: string;
  message: string;
  error?: string | null;
  headless: boolean;
  keep_open: boolean;
  started_at?: number | null;
  updated_at?: number | null;
  last_used_at?: number | null;
  active_operations: number;
  idle_timeout_seconds: number;
};

const BACKEND_UNAVAILABLE = "后端服务未启动：请运行 python3 scripts/web_api.py，或打开 http://127.0.0.1:7860";
const SEARCH_RESULT_LIMIT = 50;

type ResultChip = {
  label: string;
  value: string;
  tone: "format" | "size" | "language" | "year" | "local" | "success" | "danger" | "warning";
};

function buildResultChips(book: SearchResult): ResultChip[] {
  const chips: ResultChip[] = [];
  if (book.extension?.trim()) {
    chips.push({ label: "格式", value: book.extension.trim().toUpperCase(), tone: "format" });
  }
  if (book.filesize?.trim()) {
    chips.push({ label: "大小", value: book.filesize.trim(), tone: "size" });
  }
  if (book.language?.trim()) {
    chips.push({ label: "语言", value: book.language.trim(), tone: "language" });
  }
  if (book.year?.trim()) {
    chips.push({ label: "年份", value: book.year.trim(), tone: "year" });
  }
  return chips;
}

function resultSubtitle(book: SearchResult): string {
  const parts = [book.author, book.publisher].map((part) => part?.trim()).filter(Boolean);
  return parts.length ? parts.join(" · ") : book.details || "暂无详情";
}

function canonicalBookKey(url?: string | null): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/\/+/g, "/").replace(/^\/|\/$/g, "");
    const match = path.match(/(?:^|\/)(book\/[^/?#]+(?:\/[^/?#]+)?)/);
    return match?.[1] || path || url.split(/[?#]/)[0].replace(/\/$/g, "");
  } catch {
    const path = url.split(/[?#]/)[0].replace(/\/+/g, "/").replace(/^\/|\/$/g, "");
    const match = path.match(/(?:^|\/)(book\/[^/?#]+(?:\/[^/?#]+)?)/);
    return match?.[1] || path;
  }
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size <= 0) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function formatUpdatedAt(seconds?: number): string {
  if (!seconds) return "";
  return new Date(seconds * 1000).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function statusText(status?: string | null, stage?: string | null): string {
  const text = stage || status || "unknown";
  const map: Record<string, string> = {
    queued: "排队",
    running: "运行中",
    downloading: "下载中",
    downloaded: "已下载",
    converting: "处理中",
    processed: "已处理",
    uploading: "上传中",
    uploaded: "已上传",
    completed: "完成",
    failed: "失败",
    ready: "就绪",
    pending: "待处理",
    stopped: "未启动",
    starting: "启动中",
    busy: "忙碌",
    idle_timeout: "空闲关闭",
    crashed: "已异常",
  };
  return map[text] || text;
}

function browserCardState(status?: string): "ready" | "pending" | "problem" {
  if (status === "running") return "ready";
  if (status === "busy" || status === "starting") return "pending";
  return "problem";
}

function assetHasParts(asset: LocalAsset): boolean {
  return Boolean(asset.parts?.length);
}

function uploadSources(asset: LocalAsset): UploadSource[] {
  if (asset.upload_sources?.length) return asset.upload_sources;
  if (asset.parts?.length) return asset.parts.map((part) => ({ ...part, kind: "part", total: asset.parts?.length || 0 }));
  const uploaded = Boolean(asset.stage === "uploaded" || asset.uploads?.some((upload) => upload.status === "completed" && (upload.source_id || upload.source_ids?.length)));
  return [{
    ...(asset.processed_file || asset.original_file || {
      path: asset.local_path,
      filename: asset.filename,
      extension: asset.extension,
      size: asset.size,
    }),
    kind: "file",
    index: 1,
    total: 1,
    status: uploaded ? "uploaded" : asset.status === "failed" ? "failed" : assetIsBusy(asset) ? "uploading" : "ready",
    source_id: asset.result?.source_id as string | null | undefined,
    error: asset.error,
  }];
}

function uploadSummary(asset: LocalAsset): UploadSummary {
  if (asset.upload_summary) {
    if (assetIsBusy(asset) && asset.upload_summary.state !== "uploaded") {
      return {
        ...asset.upload_summary,
        uploading: Math.max(asset.upload_summary.uploading, 1),
        ready: Math.max(asset.upload_summary.total - asset.upload_summary.uploaded - Math.max(asset.upload_summary.uploading, 1) - asset.upload_summary.failed, 0),
        state: "uploading",
      };
    }
    return asset.upload_summary;
  }
  const sources = uploadSources(asset);
  const uploaded = sources.filter((source) => source.status === "uploaded").length;
  const failed = sources.filter((source) => source.status === "failed").length;
  const uploading = sources.filter((source) => source.status === "uploading").length;
  const total = sources.length;
  return {
    total,
    uploaded,
    failed,
    uploading,
    ready: Math.max(total - uploaded - failed - uploading, 0),
    state: uploaded === total ? "uploaded" : uploading ? "uploading" : failed ? "failed" : total ? "ready" : "empty",
  };
}

function assetHasSuccessfulUpload(asset: LocalAsset): boolean {
  const summary = asset.upload_summary;
  if (summary) return summary.total > 0 && summary.uploaded === summary.total;
  return Boolean(asset.stage === "uploaded" || asset.uploads?.some((upload) => upload.status === "completed" && (upload.source_id || upload.source_ids?.length)));
}

function assetIsBusy(asset: LocalAsset): boolean {
  return ["queued", "running"].includes(asset.status) || ["downloading", "converting", "uploading"].includes(asset.stage || "");
}

function assetStatusLine(asset: LocalAsset): string {
  const summary = uploadSummary(asset);
  const sourceText = summary.total > 1 ? `${summary.total} 个来源` : "1 个来源";
  const progressText = summary.total ? `已传 ${summary.uploaded}/${summary.total}` : "未生成来源";
  const stateText = summary.failed ? `失败 ${summary.failed}` : summary.uploading ? `上传中 ${summary.uploaded}/${summary.total}` : progressText;
  const parts = [(asset.extension || "file").toUpperCase(), formatBytes(asset.size), sourceText, stateText];
  if (asset.updated_at) parts.push(formatUpdatedAt(asset.updated_at));
  return parts.join(" · ");
}

function assetLocalState(asset: LocalAsset): "failed" | "uploading" | "uploaded" | "processed" | "downloaded" {
  const summary = uploadSummary(asset);
  if (asset.status === "failed" || summary.failed > 0) return "failed";
  if (assetIsBusy(asset) || summary.uploading > 0) return "uploading";
  if (summary.total > 0 && summary.uploaded === summary.total) return "uploaded";
  if (summary.total > 1 || assetHasParts(asset) || asset.stage === "processed") return "processed";
  return "downloaded";
}

function localMatchChips(match: LocalAsset | null, count = 0): ResultChip[] {
  if (!match) return [{ label: "本地", value: "未下载", tone: "warning" }];
  const summary = uploadSummary(match);
  const state = assetLocalState(match);
  const chips: ResultChip[] = [];
  if (count > 1) chips.push({ label: "本地", value: `${count} 份`, tone: "local" });
  if (state === "uploaded") chips.push({ label: "状态", value: `已传 ${summary.uploaded}/${summary.total}`, tone: "success" });
  else if (state === "failed") chips.push({ label: "状态", value: summary.failed ? `失败 ${summary.failed}` : "失败", tone: "danger" });
  else if (state === "uploading") chips.push({ label: "状态", value: "进行中", tone: "warning" });
  else if (state === "processed") chips.push({ label: "本地", value: summary.total > 1 ? `已分片 ${summary.total}` : "已处理", tone: "local" });
  else chips.push({ label: "本地", value: "已下载", tone: "local" });
  return chips;
}

function progressPercent(task?: UploadTask | null): number {
  const value = task?.progress?.percent;
  if (typeof value === "number" && Number.isFinite(value)) return Math.max(0, Math.min(100, value));
  if (task?.status === "completed") return 100;
  if (task?.status === "failed") return 100;
  if (task?.stage === "downloading") return 45;
  if (task?.stage === "converting") return 62;
  if (task?.stage === "uploading") return 78;
  return task ? 8 : 0;
}

function taskFailureKind(task?: UploadTask | null): "download" | "upload" | "process" | "task" {
  const label = `${task?.progress?.label || ""} ${task?.stage || ""} ${task?.error || ""}`;
  if (/下载|download/i.test(label)) return "download";
  if (/处理|分片|convert|process/i.test(label)) return "process";
  if (/上传|upload|source/i.test(label)) return "upload";
  return "task";
}

function taskResultChips(task: UploadTask | null, selectedAction: string): ResultChip[] {
  if (!task) return [];
  if (task.status === "failed") {
    return [{ label: "任务", value: taskFailureKind(task) === "download" ? "下载失败" : "失败", tone: "danger" }];
  }
  if (task.status === "running" || task.status === "queued") {
    return [{ label: "任务", value: selectedAction === "upload" ? "上传中" : "下载中", tone: "warning" }];
  }
  return [];
}

function processedSummary(asset: LocalAsset): string {
  const summary = uploadSummary(asset);
  if (summary.total > 1) return `${summary.total} 个可上传来源`;
  if (summary.total === 1) return "1 个可上传来源";
  if (asset.processed_file?.filename && asset.processed_file.path !== asset.original_file?.path) return asset.processed_file.filename;
  if (asset.stage === "processed" || asset.final_file) return "已处理，可直接上传";
  return "未处理";
}

function uploadButtonText(asset: LocalAsset, compact = false): string {
  const summary = uploadSummary(asset);
  if (busyKeyForLocal(asset) === "busy") return "上传中";
  if (summary.total === 0) return "无来源";
  if (summary.uploaded === summary.total) return compact ? "已传" : "已全部上传";
  if (summary.failed > 0 || summary.uploaded > 0) return compact ? `重传 ${summary.total}` : `重新上传全部 ${summary.total} 个来源`;
  return compact ? `上传 ${summary.total}` : `上传 ${summary.total} 个来源`;
}

function busyKeyForLocal(asset: LocalAsset): "busy" | "idle" {
  return assetIsBusy(asset) ? "busy" : "idle";
}

function sourceBusyKey(asset: LocalAsset, source: UploadSource): string {
  return `source:${asset.task_id}:${source.path}`;
}

function updateSourceStatus(asset: LocalAsset, sourcePath: string, status: string): LocalAsset {
  const nextSources = uploadSources(asset).map((source) => (
    source.path === sourcePath ? { ...source, status } : source
  ));
  const uploaded = nextSources.filter((source) => source.status === "uploaded").length;
  const failed = nextSources.filter((source) => source.status === "failed").length;
  const uploading = nextSources.filter((source) => source.status === "uploading").length;
  return {
    ...asset,
    status: status === "uploading" ? "running" : asset.status,
    stage: status === "uploading" ? "uploading" : asset.stage,
    upload_sources: nextSources,
    upload_summary: {
      total: nextSources.length,
      uploaded,
      failed,
      uploading,
      ready: Math.max(nextSources.length - uploaded - failed - uploading, 0),
      state: uploaded === nextSources.length ? "uploaded" : uploading ? "uploading" : failed ? "failed" : "ready",
    },
  };
}

function sourceStatusBucket(source: UploadSource): "uploaded" | "failed" | "uploading" | "ready" {
  if (source.status === "uploaded") return "uploaded";
  if (source.status === "failed") return "failed";
  if (source.status === "uploading") return "uploading";
  return "ready";
}

function uploadableSources(asset: LocalAsset): UploadSource[] {
  return uploadSources(asset).filter((source) => source.status !== "uploaded" && source.status !== "uploading");
}

function failedSources(asset: LocalAsset): UploadSource[] {
  return uploadSources(asset).filter((source) => source.status === "failed");
}

function readySources(asset: LocalAsset): UploadSource[] {
  return uploadSources(asset).filter((source) => source.status !== "uploaded");
}

function sourceHistory(source: UploadSource): SourceUploadRecord[] {
  return source.upload_records || [];
}

function backendUnavailableAuth(message = BACKEND_UNAVAILABLE): AuthStatus {
  return {
    zlibrary: {
      logged_in: false,
      status: "backend_unavailable",
      message,
      storage_state: "",
      session: null,
    },
    notebooklm: {
      installed: false,
      logged_in: false,
      status: "backend_unavailable",
      message,
      login_process: null,
    },
  };
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (error) {
    if (path.startsWith("/api/")) {
      throw new Error(BACKEND_UNAVAILABLE);
    }
    throw error;
  }
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    if (path.startsWith("/api/") && response.status >= 500 && !data.error) {
      throw new Error(BACKEND_UNAVAILABLE);
    }
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [query, setQuery] = useState("操作系统");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [newNotebookTitle, setNewNotebookTitle] = useState("");
  const [selectedBook, setSelectedBook] = useState<SearchResult | null>(null);
  const [selectedAction, setSelectedAction] = useState<"view" | "download" | "upload" | "local">("view");
  const [task, setTask] = useState<UploadTask | null>(null);
  const [localAssets, setLocalAssets] = useState<LocalAsset[]>([]);
  const [assetDetail, setAssetDetail] = useState<LocalAsset | null>(null);
  const [detailNotebookId, setDetailNotebookId] = useState("");
  const [detailNotebookTitle, setDetailNotebookTitle] = useState("");
  const [selectedSourcePaths, setSelectedSourcePaths] = useState<string[]>([]);
  const [expandedSourcePaths, setExpandedSourcePaths] = useState<string[]>([]);
  const [busy, setBusy] = useState("");
  const [authBusy, setAuthBusy] = useState("");
  const [message, setMessage] = useState("");
  const [logsCollapsed, setLogsCollapsed] = useState(true);
  const announcedFailureTaskRef = useRef<string>("");

  const zlibraryReady = Boolean(auth?.zlibrary.logged_in);
  const notebooklmReady = Boolean(auth?.notebooklm.logged_in);
  const zlibraryLoginActive = ["starting", "waiting", "saving"].includes(auth?.zlibrary.session?.status || "");
  const zlibraryFailed = auth?.zlibrary.status === "failed" || auth?.zlibrary.status === "backend_unavailable";
  const notebooklmLoginRunning = auth?.notebooklm.status === "login_running";
  const zlibraryCardState = zlibraryLoginActive ? "pending" : zlibraryFailed ? "problem" : zlibraryReady ? "ready" : "problem";
  const browserState = browserCardState(browser?.status);

  const canUpload = useMemo(() => {
    return Boolean(zlibraryReady && notebooklmReady && selectedBook && (selectedNotebookId || newNotebookTitle.trim()));
  }, [zlibraryReady, notebooklmReady, selectedBook, selectedNotebookId, newNotebookTitle]);

  const canUploadLocal = Boolean(notebooklmReady && (selectedNotebookId || newNotebookTitle.trim()));
  const detailNotebookTitleLabel = notebooks.find((notebook) => notebook.id === detailNotebookId)?.title || detailNotebookTitle.trim();
  const canUploadDetail = Boolean(notebooklmReady && (detailNotebookId || detailNotebookTitle.trim()));
  const localAssetsByBookKey = useMemo(() => {
    const grouped = new Map<string, LocalAsset[]>();
    for (const asset of localAssets) {
      const key = asset.book_key || canonicalBookKey(asset.zlibrary_url);
      if (!key) continue;
      const matches = grouped.get(key) || [];
      matches.push(asset);
      grouped.set(key, matches);
    }
    for (const matches of grouped.values()) {
      matches.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
    }
    return grouped;
  }, [localAssets]);
  const selectedBookKey = canonicalBookKey(selectedBook?.url);
  const selectedLocalMatches = selectedBookKey ? localAssetsByBookKey.get(selectedBookKey) || [] : [];
  const selectedLocalAsset = selectedLocalMatches[0] || null;
  const selectedTaskForBook = task && selectedBook && canonicalBookKey(task.zlibrary_url || "") === selectedBookKey ? task : null;
  const selectedTaskFailed = selectedTaskForBook?.status === "failed";
  const selectedContext = (() => {
    if (!selectedBook) return { label: "等待选择", title: "还没有选择书籍", detail: "先在左侧选择搜索结果或本地文件。" };
    if (selectedTaskFailed) {
      const kind = taskFailureKind(selectedTaskForBook);
      return {
        label: kind === "download" ? "下载失败" : kind === "upload" ? "上传失败" : "任务失败",
        title: selectedBook.title,
        detail: selectedTaskForBook.error || selectedTaskForBook.progress?.detail || "任务失败，请查看下方恢复操作或展开日志。",
      };
    }
    if (selectedTaskForBook?.status === "running" || selectedTaskForBook?.status === "queued") {
      return {
        label: selectedAction === "upload" ? "下载并上传中" : "正在下载",
        title: selectedBook.title,
        detail: selectedTaskForBook.progress?.label || statusText(selectedTaskForBook.status, selectedTaskForBook.stage),
      };
    }
    if (selectedAction === "download") {
      return {
        label: selectedLocalAsset ? "本地文件已就绪" : "准备下载",
        title: selectedBook.title,
        detail: selectedLocalAsset ? assetStatusLine(selectedLocalAsset) : "点击下载后会保存到本地文件列表。",
      };
    }
    if (selectedAction === "upload") {
      return {
        label: "准备上传",
        title: selectedBook.title,
        detail: selectedLocalAsset ? `将复用本地文件：${assetStatusLine(selectedLocalAsset)}` : "会先下载书籍，再处理并上传到知识库。",
      };
    }
    if (selectedLocalAsset) {
      return {
        label: "本地已有",
        title: selectedBook.title,
        detail: assetStatusLine(selectedLocalAsset),
      };
    }
    return { label: "已选择", title: selectedBook.title, detail: "可以下载到本地，或选择知识库后直接下载并上传。" };
  })();

  async function loadAuthStatus(silent = false) {
    if (!silent) setAuthBusy("status");
    try {
      const data = await api<AuthStatus>("/api/auth/status");
      setAuth(data);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "读取登录状态失败";
      setAuth(backendUnavailableAuth(errorMessage));
      setMessage(errorMessage);
    } finally {
      if (!silent) setAuthBusy("");
    }
  }

  async function loadBrowserStatus(silent = false) {
    if (!silent) setAuthBusy("browser-status");
    try {
      const data = await api<BrowserStatus>("/api/browser/status");
      setBrowser(data);
    } catch (error) {
      setBrowser({
        status: "backend_unavailable",
        message: error instanceof Error ? error.message : BACKEND_UNAVAILABLE,
        headless: true,
        keep_open: false,
        active_operations: 0,
        idle_timeout_seconds: 0,
      });
    } finally {
      if (!silent) setAuthBusy("");
    }
  }

  async function runBrowserAction(path: string, busyKey: string, body: Record<string, unknown> = {}) {
    setAuthBusy(busyKey);
    setMessage("");
    try {
      const data = await api<BrowserStatus>(path, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setBrowser(data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "浏览器操作失败");
      loadBrowserStatus(true);
    } finally {
      setAuthBusy("");
    }
  }

  async function runAuthAction(path: string, busyKey: string, successMessage?: string) {
    setAuthBusy(busyKey);
    setMessage("");
    try {
      const data = await api<AuthStatus>(path, { method: "POST" });
      setAuth(data);
      if (successMessage) setMessage(successMessage);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "登录操作失败";
      if (errorMessage.includes("后端服务未启动")) {
        setAuth(backendUnavailableAuth(errorMessage));
      }
      setMessage(errorMessage);
    } finally {
      setAuthBusy("");
    }
  }

  async function loadNotebooks() {
    if (auth && !auth.notebooklm.logged_in) {
      setNotebooks([]);
      setSelectedNotebookId("");
      setMessage(auth.notebooklm.message || "请先登录 NotebookLM");
      return;
    }

    setBusy("notebooks");
    setMessage("");
    try {
      const data = await api<{ notebooks: Notebook[] }>("/api/notebooks");
      setNotebooks(data.notebooks);
      if (!selectedNotebookId && data.notebooks[0]) {
        setSelectedNotebookId(data.notebooks[0].id);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取知识库失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLocalAssets(silent = false) {
    if (!silent) setBusy("local-assets");
    try {
      const data = await api<{ assets: LocalAsset[] }>("/api/local-files");
      setLocalAssets(data.assets);
    } catch (error) {
      if (!silent) setMessage(error instanceof Error ? error.message : "读取本地文件失败");
    } finally {
      if (!silent) setBusy("");
    }
  }

  async function reconcileTaskUpdate(data: UploadTask, options: { announceFailure?: boolean; refreshPeripheral?: boolean } = {}) {
    const announceFailure = options.announceFailure ?? true;
    const refreshPeripheral = options.refreshPeripheral ?? false;
    setTask(data);
    await loadLocalAssets(true);
    if (data.status === "completed" || data.status === "failed" || refreshPeripheral) {
      await Promise.allSettled([
        loadBrowserStatus(true),
        loadAuthStatus(true),
      ]);
    }
    if (announceFailure && data.status === "failed" && announcedFailureTaskRef.current !== data.id) {
      announcedFailureTaskRef.current = data.id;
      setMessage(`${data.progress?.label || "任务失败"}：${data.error || data.progress?.detail || "请查看任务日志"}`);
    }
  }

  async function searchBooks(event?: React.FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    if (auth && !auth.zlibrary.logged_in) {
      setMessage(auth.zlibrary.message || "请先登录 Z-Library");
      return;
    }

    setBusy("search");
    setMessage("");
    setSelectedBook(null);
    setSelectedAction("view");
    try {
      const data = await api<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(query)}&limit=${SEARCH_RESULT_LIMIT}`);
      setResults(data.results);
      if (data.results[0]) {
        setSelectedBook(data.results[0]);
        setSelectedAction("view");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "搜索失败");
    } finally {
      setBusy("");
    }
  }

  async function createNotebook() {
    if (!newNotebookTitle.trim()) return;
    if (auth && !auth.notebooklm.logged_in) {
      setMessage(auth.notebooklm.message || "请先登录 NotebookLM");
      return;
    }

    setBusy("create");
    setMessage("");
    try {
      const data = await api<{ notebook: Notebook }>("/api/notebooks", {
        method: "POST",
        body: JSON.stringify({ title: newNotebookTitle.trim() }),
      });
      setNotebooks((items) => [data.notebook, ...items]);
      setSelectedNotebookId(data.notebook.id);
      setNewNotebookTitle("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "创建知识库失败");
    } finally {
      setBusy("");
    }
  }

  async function downloadBook(book: SearchResult) {
    if (!zlibraryReady) {
      setMessage("请先完成 Z-Library 登录");
      return;
    }

    const matches = localAssetsByBookKey.get(canonicalBookKey(book.url)) || [];
    if (matches.length > 0) {
      const latest = matches[0];
      const ok = window.confirm(`本地已经有这本书：${latest.filename}\n\n继续下载会生成新的本地任务，不会覆盖旧文件。是否继续？`);
      if (!ok) {
        setSelectedBook(book);
        setSelectedAction("local");
        openAssetDetail(latest);
        return;
      }
    }

    setBusy(`download:${book.url}`);
    setMessage("");
    try {
      const data = await api<UploadTask>("/api/download", {
        method: "POST",
        body: JSON.stringify({ zlibrary_url: book.url }),
      });
      setSelectedBook(book);
      setSelectedAction("download");
      await reconcileTaskUpdate(data, { announceFailure: false });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "下载启动失败");
    } finally {
      setBusy("");
    }
  }

  async function uploadBook(book = selectedBook) {
    if (!book) return;
    if (!zlibraryReady || !notebooklmReady) {
      setMessage("请先完成 Z-Library 和 NotebookLM 登录");
      return;
    }
    if (!(selectedNotebookId || newNotebookTitle.trim())) {
      setMessage("请先选择或创建 NotebookLM 知识库");
      return;
    }

    setBusy("upload");
    setMessage("");
    try {
      const data = await api<UploadTask>("/api/upload", {
        method: "POST",
        body: JSON.stringify({
          zlibrary_url: book.url,
          notebook_id: selectedNotebookId || undefined,
          notebook_title: selectedNotebookId ? undefined : newNotebookTitle.trim(),
        }),
      });
      setSelectedBook(book);
      setSelectedAction("upload");
      await reconcileTaskUpdate(data, { announceFailure: false });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传启动失败");
    } finally {
      setBusy("");
    }
  }

  async function uploadLocalAsset(asset: LocalAsset) {
    if (!canUploadLocal) {
      setMessage("请先登录 NotebookLM 并选择或创建知识库");
      return;
    }

    setBusy(`local:${asset.local_path}`);
    setMessage("");
    try {
      const data = await api<UploadTask>("/api/upload-local", {
        method: "POST",
        body: JSON.stringify({
          task_id: asset.task_id,
          local_path: asset.local_path,
          notebook_id: selectedNotebookId || undefined,
          notebook_title: selectedNotebookId ? undefined : newNotebookTitle.trim(),
        }),
      });
      await reconcileTaskUpdate(data, { announceFailure: false });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "本地上传启动失败");
    } finally {
      setBusy("");
    }
  }

  async function uploadSingleSource(asset: LocalAsset, source: UploadSource) {
    if (!canUploadDetail) {
      setMessage("请先在详情页选择或创建知识库");
      return;
    }

    const key = sourceBusyKey(asset, source);
    setBusy(key);
    setMessage("");
    setAssetDetail((current) => (current?.task_id === asset.task_id ? updateSourceStatus(current, source.path, "uploading") : current));
    setLocalAssets((items) => items.map((item) => (
      item.task_id === asset.task_id ? updateSourceStatus(item, source.path, "uploading") : item
    )));
    try {
      const data = await api<UploadTask>("/api/upload-source", {
        method: "POST",
        body: JSON.stringify({
          task_id: asset.task_id,
          source_path: source.path,
          notebook_id: detailNotebookId || undefined,
          notebook_title: detailNotebookId ? undefined : detailNotebookTitle.trim(),
        }),
      });
      await reconcileTaskUpdate(data, { announceFailure: false });
    } catch (error) {
      const message = error instanceof Error ? error.message : "单个来源上传启动失败";
      setMessage(message);
      await loadLocalAssets(true);
    } finally {
      setBusy("");
    }
  }

  async function uploadSelectedSources(asset: LocalAsset, sources: UploadSource[]) {
    if (!canUploadDetail) {
      setMessage("请先在详情页选择或创建知识库");
      return;
    }
    const sourcePaths = sources.map((source) => source.path);
    if (!sourcePaths.length) {
      setMessage("请先勾选要上传的来源");
      return;
    }

    const key = `sources:${asset.task_id}`;
    setBusy(key);
    setMessage("");
    setAssetDetail((current) => {
      if (current?.task_id !== asset.task_id) return current;
      return sourcePaths.reduce((next, sourcePath) => updateSourceStatus(next, sourcePath, "uploading"), current);
    });
    setLocalAssets((items) => items.map((item) => {
      if (item.task_id !== asset.task_id) return item;
      return sourcePaths.reduce((next, sourcePath) => updateSourceStatus(next, sourcePath, "uploading"), item);
    }));
    try {
      const data = await api<UploadTask>("/api/upload-sources", {
        method: "POST",
        body: JSON.stringify({
          task_id: asset.task_id,
          source_paths: sourcePaths,
          notebook_id: detailNotebookId || undefined,
          notebook_title: detailNotebookId ? undefined : detailNotebookTitle.trim(),
        }),
      });
      await reconcileTaskUpdate(data, { announceFailure: false });
      setSelectedSourcePaths([]);
    } catch (error) {
      const message = error instanceof Error ? error.message : "已选来源上传启动失败";
      setMessage(message);
      await loadLocalAssets(true);
    } finally {
      setBusy("");
    }
  }

  async function processLocalAsset(asset: LocalAsset, strategy?: "keep" | "replace" | "version") {
    if (uploadSources(asset).length > 0 && !strategy) {
      setAssetDetail(asset);
      setMessage("这个文件已经有可上传来源，请在详情页选择保留、覆盖或生成新版本");
      return;
    }
    setBusy(`process:${asset.local_path}`);
    setMessage("");
    try {
      const data = await api<UploadTask>("/api/process-local", {
        method: "POST",
        body: JSON.stringify({ task_id: asset.task_id, local_path: asset.local_path, strategy }),
      });
      await reconcileTaskUpdate(data, { announceFailure: false });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "本地文件处理失败");
    } finally {
      setBusy("");
    }
  }

  function openAssetDetail(asset: LocalAsset) {
    setAssetDetail(asset);
    setSelectedAction("local");
    setDetailNotebookId(selectedNotebookId);
    setDetailNotebookTitle(selectedNotebookId ? "" : newNotebookTitle);
    setSelectedSourcePaths(uploadableSources(asset).map((source) => source.path));
    setExpandedSourcePaths([]);
  }

  useEffect(() => {
    loadAuthStatus();
    loadBrowserStatus(true);
    loadLocalAssets(true);
  }, []);

  useEffect(() => {
    if (auth?.notebooklm.logged_in) {
      loadNotebooks();
    }
  }, [auth?.notebooklm.logged_in]);

  useEffect(() => {
    if (!auth || (!zlibraryLoginActive && !notebooklmLoginRunning && !["starting", "busy"].includes(browser?.status || ""))) return;
    const timer = window.setInterval(() => {
      loadAuthStatus(true);
      loadBrowserStatus(true);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [auth?.zlibrary.session?.status, auth?.notebooklm.status, browser?.status]);

  useEffect(() => {
    if (!task?.id || task.status === "completed" || task.status === "failed") return;
    const taskId = task.id;
    const timer = window.setInterval(async () => {
      try {
        const data = await api<UploadTask>(`/api/tasks/${taskId}`);
        await reconcileTaskUpdate(data);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "任务状态读取失败");
        await loadLocalAssets(true);
        await loadBrowserStatus(true);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [task?.id, task?.status]);

  useEffect(() => {
    if (!assetDetail) return;
    const latest = localAssets.find((asset) => asset.local_path === assetDetail.local_path || asset.task_id === assetDetail.task_id);
    if (latest && latest !== assetDetail) {
      setAssetDetail(latest);
    }
  }, [localAssets, assetDetail]);

  const detailSources = assetDetail ? uploadSources(assetDetail) : [];
  const selectedDetailSources = detailSources.filter((source) => selectedSourcePaths.includes(source.path));
  const detailUploadableSources = assetDetail ? uploadableSources(assetDetail) : [];
  const detailFailedSources = assetDetail ? failedSources(assetDetail) : [];
  const detailReadySources = assetDetail ? readySources(assetDetail) : [];
  const selectedReadySources = selectedDetailSources.filter((source) => source.status !== "uploaded" && source.status !== "uploading");
  const allDetailUploadableSelected = detailUploadableSources.length > 0 && detailUploadableSources.every((source) => selectedSourcePaths.includes(source.path));
  const detailBatchBusy = assetDetail ? busy === `sources:${assetDetail.task_id}` : false;

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Local Reading Pipeline</p>
          <h1>Z-Library to NotebookLM Workbench</h1>
          <p className="hero-copy">搜索书籍，选择或创建 NotebookLM 知识库，然后把内容送进去。</p>
        </div>
        <div className="status-strip">
          <div className={`auth-card ${zlibraryCardState}`}>
            <div className="auth-main">
              {zlibraryCardState === "ready" ? <CheckCircle2 size={18} /> : zlibraryCardState === "pending" ? <Loader2 className="spin" size={18} /> : <AlertTriangle size={18} />}
              <div>
                <span>Z-Library 会话</span>
                <small>{auth?.zlibrary.message || "正在读取状态..."}</small>
              </div>
            </div>
            <div className="auth-actions">
              {zlibraryLoginActive ? (
                <>
                  <button className="mini-button" onClick={() => runAuthAction("/api/auth/zlibrary/complete", "zlibrary-complete")} disabled={authBusy === "zlibrary-complete"}>
                    完成登录
                  </button>
                  <button className="mini-button ghost" onClick={() => runAuthAction("/api/auth/zlibrary/cancel", "zlibrary-cancel")} disabled={authBusy === "zlibrary-cancel"}>
                    取消
                  </button>
                </>
              ) : (
                <button className="mini-button" onClick={() => runAuthAction("/api/auth/zlibrary/start", "zlibrary-start")} disabled={authBusy === "zlibrary-start"}>
                  {authBusy === "zlibrary-start" ? <Loader2 className="spin" size={14} /> : <LogIn size={14} />}
                  {zlibraryReady ? "重新登录" : "登录"}
                </button>
              )}
            </div>
          </div>

          <div className={`auth-card ${notebooklmReady ? "ready" : notebooklmLoginRunning ? "pending" : "problem"}`}>
            <div className="auth-main">
              {notebooklmReady ? <CheckCircle2 size={18} /> : notebooklmLoginRunning ? <Loader2 className="spin" size={18} /> : <XCircle size={18} />}
              <div>
                <span>NotebookLM CLI</span>
                <small>{auth?.notebooklm.message || "正在读取状态..."}</small>
              </div>
            </div>
            <div className="auth-actions">
              {notebooklmLoginRunning ? (
                <button className="mini-button ghost" onClick={() => runAuthAction("/api/auth/notebooklm/cancel", "notebooklm-cancel")} disabled={authBusy === "notebooklm-cancel"}>
                  取消
                </button>
              ) : (
                <button className="mini-button" onClick={() => runAuthAction("/api/auth/notebooklm/start", "notebooklm-start")} disabled={authBusy === "notebooklm-start" || auth?.notebooklm.installed === false}>
                  {authBusy === "notebooklm-start" ? <Loader2 className="spin" size={14} /> : <LogIn size={14} />}
                  {notebooklmReady ? "重新登录" : "登录"}
                </button>
              )}
              <button className="mini-button ghost" onClick={() => loadAuthStatus()} disabled={authBusy === "status"}>
                刷新
              </button>
            </div>
          </div>

          <div className={`auth-card ${browserState}`}>
            <div className="auth-main">
              {browserState === "ready" ? <CheckCircle2 size={18} /> : browserState === "pending" ? <Loader2 className="spin" size={18} /> : <AlertTriangle size={18} />}
              <div>
                <span>自动化浏览器</span>
                <small>
                  {statusText(browser?.status, null)} · {browser?.message || "正在读取状态..."}
                  {browser?.active_operations ? ` · ${browser.active_operations} 个任务` : ""}
                </small>
              </div>
            </div>
            <div className="auth-actions browser-actions">
              <button
                className="mini-button"
                onClick={() => runBrowserAction("/api/browser/start", "browser-start", { headless: true, keep_open: true })}
                disabled={authBusy === "browser-start" || browser?.status === "running" || browser?.status === "busy"}
              >
                {authBusy === "browser-start" ? <Loader2 className="spin" size={14} /> : <LogIn size={14} />}
                启动
              </button>
              <button
                className="mini-button ghost"
                onClick={() => runBrowserAction("/api/browser/close", "browser-close")}
                disabled={authBusy === "browser-close" || !browser || ["stopped", "idle_timeout", "backend_unavailable"].includes(browser.status)}
              >
                关闭
              </button>
              <button
                className="mini-button ghost"
                onClick={() => runBrowserAction("/api/browser/restart", "browser-restart", { headless: true, keep_open: true })}
                disabled={authBusy === "browser-restart"}
              >
                重启
              </button>
            </div>
          </div>
        </div>
      </section>

      <div className={`notice ${message ? "visible" : ""}`} role="status" aria-live="polite">
        {message || " "}
      </div>

      <section className={`workspace ${logsCollapsed ? "logs-collapsed" : ""}`}>
        <div className="panel search-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Step 1</p>
              <h2>搜索书籍</h2>
            </div>
            <BookOpen size={24} />
          </div>
          <form className="search-form" onSubmit={searchBooks}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入书名、作者或关键词" />
            <button type="submit" disabled={busy === "search"}>
              {busy === "search" ? <Loader2 className="spin" size={18} /> : <Search size={18} />}
              搜索
            </button>
          </form>
          <div className="results-summary">
            {busy === "search" ? "正在搜索..." : results.length ? `显示 ${results.length} 条结果` : " "}
          </div>
          <div className="results-list">
            {results.length ? (
              results.map((book, index) => {
                const bookKey = canonicalBookKey(book.url);
                const localMatches = bookKey ? localAssetsByBookKey.get(bookKey) || [] : [];
                const localMatch = localMatches[0] || null;
                const resultTask = task && canonicalBookKey(task.zlibrary_url || "") === bookKey ? task : null;
                const chips = [...buildResultChips(book), ...localMatchChips(localMatch, localMatches.length), ...taskResultChips(resultTask, selectedAction)];
                return (
                  <div
                    className={`result-card ${selectedBook?.url === book.url ? "selected" : ""} ${localMatch ? `has-local ${assetLocalState(localMatch)}` : ""}`}
                    key={book.url}
                  >
                    <button
                      className="result-select"
                      onClick={() => {
                        setSelectedBook(book);
                        setSelectedAction(localMatch ? "local" : "view");
                      }}
                    >
                      <span className="result-index">{index + 1}</span>
                      <span className="result-content">
                        <strong>{book.title}</strong>
                        {chips.length > 0 && (
                          <span className="result-meta" aria-label="书籍文件信息">
                            {chips.map((chip) => (
                              <span className={`meta-chip ${chip.tone}`} key={`${chip.label}-${chip.value}`}>
                                <span>{chip.label}</span>
                                <b>{chip.value}</b>
                              </span>
                            ))}
                          </span>
                        )}
                        <small>{resultSubtitle(book)}</small>
                      </span>
                    </button>
                    <div className="result-actions">
                      <button
                        className="mini-button ghost"
                        onClick={() => downloadBook(book)}
                        disabled={!zlibraryReady || busy === `download:${book.url}`}
                        title={localMatch ? "本地已有，点击后可选择是否再下载一个新版本" : "下载到本地文件列表"}
                      >
                        {busy === `download:${book.url}` ? <Loader2 className="spin" size={14} /> : <Download size={14} />}
                        {localMatch ? "再下载" : "下载"}
                      </button>
                      {localMatch && (
                        <button
                          className="mini-button ghost"
                          onClick={() => {
                            setSelectedBook(book);
                            setSelectedAction("local");
                            openAssetDetail(localMatch);
                          }}
                        >
                          <Eye size={14} />
                          本地
                        </button>
                      )}
                      <button
                        className="mini-button"
                        onClick={() => uploadBook(book)}
                        disabled={!zlibraryReady || !notebooklmReady || !(selectedNotebookId || newNotebookTitle.trim()) || busy === "upload"}
                      >
                        {busy === "upload" ? <Loader2 className="spin" size={14} /> : <UploadCloud size={14} />}
                        下载并上传
                      </button>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="empty-state">输入关键词搜索，结果会显示在这里。</div>
            )}
          </div>
        </div>

        <div className="panel notebook-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Step 2</p>
              <h2>选择知识库</h2>
            </div>
            <button className="icon-button" onClick={loadNotebooks} title="刷新知识库">
              <RefreshCcw size={18} className={busy === "notebooks" ? "spin" : ""} />
            </button>
          </div>

          <label className="field-label">已有知识库</label>
          <select
            value={selectedNotebookId}
            onChange={(event) => {
              setSelectedNotebookId(event.target.value);
              if (event.target.value) setNewNotebookTitle("");
            }}
          >
            <option value="">不选择，使用新知识库</option>
            {notebooks.map((notebook) => (
              <option key={notebook.id} value={notebook.id}>
                {notebook.title}
              </option>
            ))}
          </select>

          <div className="divider">或创建新的</div>
          <div className="create-row">
            <input
              value={newNotebookTitle}
              onChange={(event) => {
                setNewNotebookTitle(event.target.value);
                if (event.target.value.trim()) setSelectedNotebookId("");
              }}
              placeholder="新知识库名称"
            />
            <button onClick={createNotebook} disabled={busy === "create" || !newNotebookTitle.trim()}>
              {busy === "create" ? <Loader2 className="spin" size={18} /> : <Plus size={18} />}
              创建
            </button>
          </div>

          <div className="selection-box">
            <Database size={20} />
            <div>
              <span>{selectedContext.label}</span>
              <strong>{selectedContext.title}</strong>
              <small>{selectedContext.detail}</small>
            </div>
          </div>

          {task && (
            <div className={`task-progress-card ${task.status}`}>
              <div className="task-progress-head">
                <span>{task.progress?.label || statusText(task.status, task.stage)}</span>
                <b>{progressPercent(task)}%</b>
              </div>
              <div className="task-progress-track" aria-label="任务进度">
                <div style={{ width: `${progressPercent(task)}%` }} />
              </div>
              <small>{task.progress?.detail || task.logs?.[task.logs.length - 1] || "等待任务更新"}</small>
              {task.status === "failed" && (
                <div className="task-recovery">
                  <strong>{task.error || "任务失败"}</strong>
                  <div className="task-recovery-actions">
                    {selectedBook && taskFailureKind(task) === "download" && (
                      <button className="mini-button" onClick={() => downloadBook(selectedBook)} disabled={!zlibraryReady || busy === `download:${selectedBook.url}`}>
                        {busy === `download:${selectedBook.url}` ? <Loader2 className="spin" size={14} /> : <Download size={14} />}
                        重试下载
                      </button>
                    )}
                    {taskFailureKind(task) === "download" && (
                      <button
                        className="mini-button ghost"
                        onClick={() => runBrowserAction("/api/browser/restart", "browser-restart", { headless: true, keep_open: true })}
                        disabled={authBusy === "browser-restart"}
                      >
                        <RefreshCcw size={14} />
                        重启浏览器
                      </button>
                    )}
                    {selectedLocalAsset && taskFailureKind(task) !== "download" && (
                      <button className="mini-button" onClick={() => openAssetDetail(selectedLocalAsset)}>
                        <Eye size={14} />
                        打开本地详情
                      </button>
                    )}
                    <button className="mini-button ghost" onClick={() => setLogsCollapsed(false)}>
                      <PanelRightOpen size={14} />
                      查看日志
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="local-assets">
            <div className="local-assets-heading">
              <span>本地文件</span>
              <button className="mini-button ghost" onClick={() => loadLocalAssets()} disabled={busy === "local-assets"}>
                <RefreshCcw size={14} className={busy === "local-assets" ? "spin" : ""} />
                刷新
              </button>
            </div>
            <div className="local-assets-list">
              {localAssets.length ? (
                localAssets.map((asset) => (
                  <div className={`local-asset ${asset.status}`} key={`${asset.task_id}-${asset.local_path}`}>
                    <div className="local-asset-main">
                      <strong>{asset.filename}</strong>
                      <small>
                        {assetStatusLine(asset)}
                      </small>
                      {asset.error && <em>{asset.error}</em>}
                    </div>
                    <div className="local-asset-actions">
                      <button className="mini-button ghost" onClick={() => openAssetDetail(asset)}>
                        <Eye size={14} />
                        详情
                      </button>
                      <button
                        className="mini-button ghost"
                        onClick={() => processLocalAsset(asset)}
                        disabled={busy === `process:${asset.local_path}` || assetIsBusy(asset)}
                      >
                        {busy === `process:${asset.local_path}` ? <Loader2 className="spin" size={14} /> : <Scissors size={14} />}
                        分片
                      </button>
                      <button
                        className="mini-button"
                        onClick={() => uploadLocalAsset(asset)}
                        disabled={!canUploadLocal || busy === `local:${asset.local_path}` || assetIsBusy(asset) || assetHasSuccessfulUpload(asset) || uploadSummary(asset).total === 0}
                        title={!canUploadLocal ? "请先选择或创建知识库" : assetHasSuccessfulUpload(asset) ? "所有来源已上传" : ""}
                      >
                        {busy === `local:${asset.local_path}` ? <Loader2 className="spin" size={14} /> : <UploadCloud size={14} />}
                        {busy === `local:${asset.local_path}` ? "上传中" : uploadButtonText(asset, true)}
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="local-empty">暂无本地下载文件</div>
              )}
            </div>
          </div>

          <button className="upload-button" onClick={() => uploadBook()} disabled={!canUpload || busy === "upload"}>
            {busy === "upload" ? <Loader2 className="spin" size={20} /> : <UploadCloud size={20} />}
            上传到 NotebookLM
          </button>
        </div>

        <div className={`panel task-panel ${logsCollapsed ? "collapsed" : "open"}`}>
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Step 3</p>
              <h2>任务日志</h2>
            </div>
            <div className="task-heading-actions">
              <span className={`task-status ${task?.status || "idle"}`}>{task?.status || "idle"}</span>
              <button
                className="icon-button"
                onClick={() => setLogsCollapsed((value) => !value)}
                title={logsCollapsed ? "展开日志" : "折叠日志"}
              >
                {logsCollapsed ? <PanelRightOpen size={17} /> : <PanelRightClose size={17} />}
              </button>
            </div>
          </div>
          {!logsCollapsed && (
            <>
              <div className="log-box">
                {task?.error && (
                  <div className="task-error">失败原因：{task.error}</div>
                )}
                {(task?.logs?.length ? task.logs : ["等待上传任务..."]).map((line, index) => (
                  <div key={`${line}-${index}`}>{line}</div>
                ))}
              </div>
              {task?.result && (
                <pre className="result-json">{JSON.stringify(task.result, null, 2)}</pre>
              )}
            </>
          )}
        </div>
      </section>

      {logsCollapsed && (
        <button className="log-floating-toggle" onClick={() => setLogsCollapsed(false)} title="展开任务日志">
          <PanelRightOpen size={16} />
          日志
          {task?.status && <span>{statusText(task.status, task.stage)}</span>}
        </button>
      )}

      {assetDetail && (
        <div className="modal-backdrop" role="presentation" onClick={() => setAssetDetail(null)}>
          <section className="asset-modal" role="dialog" aria-modal="true" aria-label="本地文件详情" onClick={(event) => event.stopPropagation()}>
            <div className="asset-modal-header">
              <div>
                <p className="eyebrow">Local Asset</p>
                <h2>{assetDetail.filename}</h2>
                <small>
                  {(assetDetail.extension || "file").toUpperCase()} · {formatBytes(assetDetail.size)} · {statusText(assetDetail.status, assetDetail.stage)}
                  {assetHasParts(assetDetail) ? ` · ${assetDetail.parts?.length} 个分片` : ""}
                </small>
              </div>
              <button className="icon-button" onClick={() => setAssetDetail(null)} title="关闭">
                <X size={18} />
              </button>
            </div>

            {assetDetail.error && <div className="modal-error">失败原因：{assetDetail.error}</div>}

            <div className="asset-toolbar">
              <div className="asset-process-group">
                <button
                  className="mini-button ghost"
                  onClick={() => processLocalAsset(assetDetail, uploadSummary(assetDetail).total ? "keep" : undefined)}
                  disabled={busy === `process:${assetDetail.local_path}` || assetIsBusy(assetDetail)}
                  title={uploadSummary(assetDetail).total ? "保留当前分片，不重新生成" : "处理文件并生成可上传来源"}
                >
                  {busy === `process:${assetDetail.local_path}` ? <Loader2 className="spin" size={14} /> : <Scissors size={14} />}
                  {uploadSummary(assetDetail).total ? "保留分片" : "处理/分片"}
                </button>
                <button
                  className="mini-button ghost warning"
                  onClick={() => processLocalAsset(assetDetail, "replace")}
                  disabled={busy === `process:${assetDetail.local_path}` || assetIsBusy(assetDetail)}
                  title="覆盖当前处理结果，旧上传记录保留为历史"
                >
                  覆盖重分片
                </button>
                <button
                  className="mini-button ghost"
                  onClick={() => processLocalAsset(assetDetail, "version")}
                  disabled={busy === `process:${assetDetail.local_path}` || assetIsBusy(assetDetail)}
                  title="生成新版本处理结果，旧上传记录保留为历史"
                >
                  新版本
                </button>
              </div>
              <div className="asset-summary-line">
                <b>{uploadSummary(assetDetail).uploaded}/{uploadSummary(assetDetail).total}</b>
                <span>{uploadSummary(assetDetail).failed ? `${uploadSummary(assetDetail).failed} 个失败` : statusText(uploadSummary(assetDetail).state, null)}</span>
              </div>
            </div>

            <div className="target-picker">
              <div>
                <label className="field-label">本次上传到</label>
                <select
                  value={detailNotebookId}
                  onChange={(event) => {
                    setDetailNotebookId(event.target.value);
                    if (event.target.value) setDetailNotebookTitle("");
                  }}
                >
                  <option value="">不选择，使用新知识库</option>
                  {notebooks.map((notebook) => (
                    <option key={notebook.id} value={notebook.id}>
                      {notebook.title}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label">新知识库名称</label>
                <input
                  value={detailNotebookTitle}
                  onChange={(event) => {
                    setDetailNotebookTitle(event.target.value);
                    if (event.target.value.trim()) setDetailNotebookId("");
                  }}
                  placeholder="留空则必须选择已有知识库"
                />
              </div>
            </div>

            {assetDetail.uploads?.[0]?.notebook_id && detailNotebookId && assetDetail.uploads[0].notebook_id !== detailNotebookId && (
              <div className="target-warning">
                本次目标：{detailNotebookTitleLabel || detailNotebookId}；历史目标：{assetDetail.uploads[0].notebook_title || assetDetail.uploads[0].notebook_id}。不同分片可以上传到不同知识库，下面每个来源会单独记录。
              </div>
            )}

            <div className="asset-detail-grid">
              <div className="detail-block">
                <span>原始文件</span>
                <strong>{assetDetail.original_file?.filename || assetDetail.filename}</strong>
                <small>{assetDetail.original_file?.path || assetDetail.downloaded_file || assetDetail.local_path}</small>
              </div>
              <div className="detail-block">
                <span>处理结果</span>
                <strong>{processedSummary(assetDetail)}</strong>
                <small>{assetDetail.processed_file?.path || assetDetail.final_file || "可点击处理/分片生成"}</small>
              </div>
              <div className="detail-block">
                <span>目标知识库</span>
                <strong>{detailNotebookTitleLabel || "未选择"}</strong>
                <small>{detailNotebookId || detailNotebookTitle.trim() || "请在上方选择本次上传目标"}</small>
              </div>
              <div className="detail-block">
                <span>来源</span>
                <strong>{assetDetail.mode || "remote"}</strong>
                <small>{assetDetail.zlibrary_url || "本地工作区文件"}</small>
              </div>
            </div>

            <div className="modal-section">
              <div className="modal-section-title">
                <strong>可上传来源</strong>
                <span>已选 {selectedReadySources.length}/{detailSources.length}</span>
              </div>
              <div className="source-batch-bar">
                <button
                  className="mini-button ghost"
                  onClick={() => setSelectedSourcePaths(allDetailUploadableSelected ? [] : detailUploadableSources.map((source) => source.path))}
                  disabled={!detailUploadableSources.length}
                >
                  {allDetailUploadableSelected ? "取消全选" : "全选可传"}
                </button>
                <button className="mini-button ghost" onClick={() => setSelectedSourcePaths(detailFailedSources.map((source) => source.path))} disabled={!detailFailedSources.length}>
                  只选失败
                </button>
                <button className="mini-button ghost" onClick={() => setSelectedSourcePaths(detailReadySources.map((source) => source.path))} disabled={!detailReadySources.length}>
                  只选未完成
                </button>
                <button
                  className="mini-button"
                  onClick={() => uploadSelectedSources(assetDetail, selectedReadySources)}
                  disabled={!canUploadDetail || detailBatchBusy || assetIsBusy(assetDetail) || selectedReadySources.length === 0}
                  title={!canUploadDetail ? "请在详情页选择或创建知识库" : selectedReadySources.length === 0 ? "请先勾选未上传来源" : ""}
                >
                  {detailBatchBusy ? <Loader2 className="spin" size={14} /> : <UploadCloud size={14} />}
                  上传已选 {selectedReadySources.length}
                </button>
                <button
                  className="mini-button ghost"
                  onClick={() => uploadSelectedSources(assetDetail, detailFailedSources)}
                  disabled={!canUploadDetail || detailBatchBusy || assetIsBusy(assetDetail) || detailFailedSources.length === 0}
                >
                  重传失败 {detailFailedSources.length}
                </button>
              </div>
              <div className="parts-table">
                {detailSources.length ? (
                  detailSources.map((source, index) => {
                    const history = sourceHistory(source);
                    const expanded = expandedSourcePaths.includes(source.path);
                    const checked = selectedSourcePaths.includes(source.path);
                    return (
                      <div className={`part-row-wrap ${sourceStatusBucket(source)}`} key={`${source.path}-${index}`}>
                        <div className="part-row">
                          <label className="source-check" title={source.status === "uploaded" ? "已上传来源默认不再选择" : "选择这个来源"}>
                            <input
                              type="checkbox"
                              checked={checked}
                              disabled={source.status === "uploaded" || source.status === "uploading"}
                              onChange={(event) => {
                                setSelectedSourcePaths((paths) => (
                                  event.target.checked
                                    ? Array.from(new Set([...paths, source.path]))
                                    : paths.filter((path) => path !== source.path)
                                ));
                              }}
                            />
                          </label>
                          <span>{source.total && source.total > 1 ? `${source.index || index + 1}/${source.total}` : "1/1"}</span>
                          <strong>{source.filename}</strong>
                          <small>{source.kind === "part" ? "分片" : "单文件"} · {formatBytes(source.size)}</small>
                          <b>{statusText(source.status, null)}</b>
                          <em>{source.last_notebook_title || source.source_id || source.error || "未上传"}</em>
                          <button
                            className="mini-button source-upload-button"
                            onClick={() => uploadSingleSource(assetDetail, source)}
                            disabled={!canUploadDetail || busy === sourceBusyKey(assetDetail, source) || source.status === "uploaded"}
                            title={!canUploadDetail ? "请在详情页选择或创建知识库" : source.status === "uploaded" ? "这个来源已经上传" : ""}
                          >
                            {busy === sourceBusyKey(assetDetail, source) ? <Loader2 className="spin" size={13} /> : <UploadCloud size={13} />}
                            {source.status === "uploaded" ? "已传" : "单传"}
                          </button>
                          <button
                            className="mini-button ghost source-record-toggle"
                            onClick={() => setExpandedSourcePaths((paths) => (
                              expanded ? paths.filter((path) => path !== source.path) : [...paths, source.path]
                            ))}
                            disabled={!history.length}
                          >
                            记录 {history.length}
                          </button>
                        </div>
                        {expanded && (
                          <div className="source-records">
                            {history.map((record, recordIndex) => (
                              <div className={`upload-record ${record.status || "pending"}`} key={`${record.updated_at || recordIndex}-${record.source_id || ""}`}>
                                <strong>{record.notebook_title || record.notebook_id || record.title || `记录 ${recordIndex + 1}`}</strong>
                                <small>
                                  {statusText(record.status, null)}
                                  {record.source_id ? ` · ${record.source_id}` : ""}
                                  {record.updated_at ? ` · ${formatUpdatedAt(record.updated_at)}` : ""}
                                </small>
                                {record.error && <em>{record.error}</em>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
                ) : (
                  <div className="modal-empty">
                    {assetDetail.stage === "processed" || assetDetail.final_file
                      ? "当前文件已处理为可直接上传文件，没有生成分片。PDF 通常直接上传；EPUB/Markdown 超过阈值才会分片。"
                      : "当前文件还没有处理/分片记录。PDF 通常直接上传；EPUB/Markdown 可点击处理/分片。"}
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
