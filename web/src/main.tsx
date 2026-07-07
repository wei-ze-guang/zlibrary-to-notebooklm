import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  Database,
  Loader2,
  LogIn,
  Plus,
  RefreshCcw,
  Search,
  UploadCloud,
  XCircle,
} from "lucide-react";
import "./styles.css";

type SearchResult = {
  title: string;
  url: string;
  details: string;
};

type Notebook = {
  id: string;
  title: string;
};

type UploadTask = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  logs: string[];
  error?: string | null;
  result?: Record<string, unknown> | null;
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

const BACKEND_UNAVAILABLE = "后端服务未启动：请运行 python3 scripts/web_api.py，或打开 http://127.0.0.1:7860";

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
  const [query, setQuery] = useState("操作系统");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [newNotebookTitle, setNewNotebookTitle] = useState("");
  const [selectedBook, setSelectedBook] = useState<SearchResult | null>(null);
  const [task, setTask] = useState<UploadTask | null>(null);
  const [busy, setBusy] = useState("");
  const [authBusy, setAuthBusy] = useState("");
  const [message, setMessage] = useState("");

  const zlibraryReady = Boolean(auth?.zlibrary.logged_in);
  const notebooklmReady = Boolean(auth?.notebooklm.logged_in);
  const zlibraryLoginActive = ["starting", "waiting", "saving"].includes(auth?.zlibrary.session?.status || "");
  const zlibraryFailed = auth?.zlibrary.status === "failed" || auth?.zlibrary.status === "backend_unavailable";
  const notebooklmLoginRunning = auth?.notebooklm.status === "login_running";
  const zlibraryCardState = zlibraryLoginActive ? "pending" : zlibraryFailed ? "problem" : zlibraryReady ? "ready" : "problem";

  const canUpload = useMemo(() => {
    return Boolean(zlibraryReady && notebooklmReady && selectedBook && (selectedNotebookId || newNotebookTitle.trim()));
  }, [zlibraryReady, notebooklmReady, selectedBook, selectedNotebookId, newNotebookTitle]);

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
    try {
      const data = await api<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(query)}&limit=12`);
      setResults(data.results);
      if (data.results[0]) {
        setSelectedBook(data.results[0]);
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

  async function uploadBook() {
    if (!selectedBook || !canUpload) return;
    if (!zlibraryReady || !notebooklmReady) {
      setMessage("请先完成 Z-Library 和 NotebookLM 登录");
      return;
    }

    setBusy("upload");
    setMessage("");
    try {
      const data = await api<UploadTask>("/api/upload", {
        method: "POST",
        body: JSON.stringify({
          zlibrary_url: selectedBook.url,
          notebook_id: selectedNotebookId || undefined,
          notebook_title: selectedNotebookId ? undefined : newNotebookTitle.trim(),
        }),
      });
      setTask(data);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传启动失败");
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    loadAuthStatus();
  }, []);

  useEffect(() => {
    if (auth?.notebooklm.logged_in) {
      loadNotebooks();
    }
  }, [auth?.notebooklm.logged_in]);

  useEffect(() => {
    if (!auth || (!zlibraryLoginActive && !notebooklmLoginRunning)) return;
    const timer = window.setInterval(() => {
      loadAuthStatus(true);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [auth?.zlibrary.session?.status, auth?.notebooklm.status]);

  useEffect(() => {
    if (!task?.id || task.status === "completed" || task.status === "failed") return;
    const taskId = task.id;
    const timer = window.setInterval(async () => {
      try {
        const data = await api<UploadTask>(`/api/tasks/${taskId}`);
        setTask(data);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "任务状态读取失败");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [task?.id, task?.status]);

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
        </div>
      </section>

      <div className={`notice ${message ? "visible" : ""}`} role="status" aria-live="polite">
        {message || " "}
      </div>

      <section className="workspace">
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
          <div className="results-list">
            {results.length ? (
              results.map((book, index) => (
                <button
                  className={`result-card ${selectedBook?.url === book.url ? "selected" : ""}`}
                  key={book.url}
                  onClick={() => setSelectedBook(book)}
                >
                  <span className="result-index">{index + 1}</span>
                  <strong>{book.title}</strong>
                  <small>{book.details || "暂无详情"}</small>
                </button>
              ))
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
              <span>准备上传</span>
              <strong>{selectedBook?.title || "还没有选择书籍"}</strong>
            </div>
          </div>

          <button className="upload-button" onClick={uploadBook} disabled={!canUpload || busy === "upload"}>
            {busy === "upload" ? <Loader2 className="spin" size={20} /> : <UploadCloud size={20} />}
            上传到 NotebookLM
          </button>
        </div>

        <div className="panel task-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Step 3</p>
              <h2>任务日志</h2>
            </div>
            <span className={`task-status ${task?.status || "idle"}`}>{task?.status || "idle"}</span>
          </div>
          <div className="log-box">
            {(task?.logs?.length ? task.logs : ["等待上传任务..."]).map((line, index) => (
              <div key={`${line}-${index}`}>{line}</div>
            ))}
          </div>
          {task?.result && (
            <pre className="result-json">{JSON.stringify(task.result, null, 2)}</pre>
          )}
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
