import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BookOpen, Database, Loader2, Plus, RefreshCcw, Search, UploadCloud } from "lucide-react";
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

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function App() {
  const [query, setQuery] = useState("操作系统");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [newNotebookTitle, setNewNotebookTitle] = useState("");
  const [selectedBook, setSelectedBook] = useState<SearchResult | null>(null);
  const [task, setTask] = useState<UploadTask | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const canUpload = useMemo(() => {
    return Boolean(selectedBook && (selectedNotebookId || newNotebookTitle.trim()));
  }, [selectedBook, selectedNotebookId, newNotebookTitle]);

  async function loadNotebooks() {
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
    loadNotebooks();
  }, []);

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
          <span><Database size={18} /> NotebookLM CLI 本地连接</span>
          <span><BookOpen size={18} /> Z-Library 本机会话复用</span>
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
