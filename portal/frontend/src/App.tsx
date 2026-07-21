import { useEffect, useState, type FormEvent } from "react";

type Tag = { id: number; name: string };
type Doc = {
  id: number;
  title: string;
  abstract: string;
  trade: string;
  source: string;
  tags: Tag[];
  created: string;
};
type Facets = { projects: Tag[]; trades: string[]; sources: string[] };
type DocResponse = { results: Doc[]; total: number; page: number; page_size: number };

const PAGE_SIZE = 20;
const DEFAULT_TRADE = ""; // default to All trades

function projectName(name: string) {
  return name === "Brookfield" ? "Brookfield shared" : name;
}

function authHeader() {
  return { Authorization: `Bearer ${localStorage.getItem("portal_token") || ""}` };
}
function token() {
  return localStorage.getItem("portal_token") || "";
}

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pw }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        localStorage.setItem("portal_token", d.token);
        onSuccess();
      })
      .catch(() => setErr("Wrong password, try again."))
      .finally(() => setBusy(false));
  };
  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <h1>Document Portal</h1>
        <p className="subtitle">Enter the password to continue.</p>
        <input
          type="password"
          placeholder="Password"
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoFocus
        />
        <button type="submit" disabled={busy}>
          {busy ? "…" : "Enter"}
        </button>
        {err && <div className="error">{err}</div>}
      </form>
    </div>
  );
}

function Viewer({ doc, id, onClose }: { doc: Doc | null; id: number; onClose: () => void }) {
  const [showPdf, setShowPdf] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    let cancelled = false;
    setSummary(null);
    fetch(`/api/documents/${id}`, { headers: authHeader() })
      .then((r) => r.json())
      .then((d) => !cancelled && setSummary(d.summary || d.abstract || ""))
      .catch(() => !cancelled && setSummary(""));
    return () => {
      cancelled = true;
    };
  }, [id]);
  return (
    <div className="viewer" onClick={onClose}>
      <div className="viewer-bar" onClick={(e) => e.stopPropagation()}>
        <span className="viewer-title">{doc?.title ?? `Document #${id}`}</span>
        <button className="toggle" onClick={() => setShowPdf((p) => !p)}>
          {showPdf ? "View Summary" : "View PDF"}
        </button>
        <a href={`/api/documents/${id}/download?token=${token()}`} target="_blank" rel="noreferrer">
          Download
        </a>
        <button onClick={onClose}>Close ✕</button>
      </div>
      <div className="viewer-text" onClick={(e) => e.stopPropagation()}>
        {showPdf ? (
          <iframe
            className="pdf-frame"
            src={`/api/documents/${id}/preview?token=${token()}`}
            title={doc?.title ?? "document"}
          />
        ) : (
          <div className="summary-pane">
            {summary === null ? "Loading…" : summary || "(No summary available yet.)"}
          </div>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [authed, setAuthed] = useState<boolean>(() => !!localStorage.getItem("portal_token"));
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState<number | "">("");
  const [trade, setTrade] = useState<string>(DEFAULT_TRADE);
  const [source, setSource] = useState<string>("");
  const [page, setPage] = useState(1);
  const [facets, setFacets] = useState<Facets>({ projects: [], trades: [], sources: [] });
  const [data, setData] = useState<DocResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  const logout = () => {
    localStorage.removeItem("portal_token");
    setAuthed(false);
    setData(null);
  };

  useEffect(() => {
    if (!authed) return;
    fetch("/api/facets", { headers: authHeader() })
      .then((r) => r.json())
      .then(setFacets)
      .catch(() => {});
  }, [authed]);

  useEffect(() => {
    setPage(1);
  }, [query, projectId, trade, source]);

  useEffect(() => {
    if (!authed) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    if (projectId !== "") params.set("tag_id", String(projectId));
    if (trade) params.set("trade", trade);
    if (source) params.set("source", source);
    params.set("page", String(page));
    params.set("page_size", String(PAGE_SIZE));
    fetch(`/api/documents?${params}`, { headers: authHeader() })
      .then((r) => {
        if (r.status === 401) {
          logout();
          throw new Error("unauthorized");
        }
        return r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`);
      })
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query, projectId, trade, source, page, authed]);

  if (!authed) return <Login onSuccess={() => setAuthed(true)} />;

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const tk = token();

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Document Portal</h1>
          <p className="subtitle">
            Search bid &amp; specification documents by project and trade.
          </p>
        </div>
        <button className="logout" onClick={logout}>
          Log out
        </button>
      </header>

      <div className="controls">
        <input
          className="search"
          placeholder="Search documents (e.g. cabinet, vanity, hardware)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value === "" ? "" : Number(e.target.value))}
        >
          <option value="">All projects</option>
          {facets.projects.map((p) => (
            <option key={p.id} value={p.id}>
              {projectName(p.name)}
            </option>
          ))}
        </select>
        <select value={trade} onChange={(e) => setTrade(e.target.value)}>
          <option value="">All trades</option>
          {facets.trades.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">All sources</option>
          {facets.sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {(trade !== DEFAULT_TRADE || projectId !== "" || query || source) && (
          <button
            className="clear"
            onClick={() => {
              setQuery("");
              setProjectId("");
              setTrade(DEFAULT_TRADE);
              setSource("");
            }}
          >
            Reset
          </button>
        )}
      </div>

      <div className="meta">
        {loading
          ? "Loading…"
          : data
            ? `${data.total} document${data.total === 1 ? "" : "s"}${trade ? ` · ${trade}` : ""}`
            : ""}
      </div>

      {error && <div className="error">Failed to load: {error}</div>}

      <div className="results">
        {!loading && data && data.results.length === 0 && (
          <div className="empty">No documents match these filters.</div>
        )}
        {data?.results.map((d) => (
          <div className="card" key={d.id} onClick={() => setOpenId(d.id)}>
            <div className="thumb-link" title="Open document">
              <img
                className="thumb"
                src={`/api/documents/${d.id}/thumb?token=${tk}`}
                alt=""
                loading="lazy"
              />
            </div>
            <div className="card-body">
              <div className="card-title">{d.title}</div>
              {d.abstract && <div className="card-abstract">{d.abstract}</div>}
              <div className="card-tags">
                {d.trade && <span className="chip trade">{d.trade}</span>}
                {d.source && <span className="chip source">{d.source}</span>}
                {d.tags.map((t) => (
                  <span key={t.id} className="chip">
                    {projectName(t.name)}
                  </span>
                ))}
              </div>
            </div>
            <div className="card-actions">
              <a
                href={`/api/documents/${d.id}/download?token=${tk}`}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
              >
                Download
              </a>
            </div>
          </div>
        ))}
      </div>

      {totalPages > 1 && data && (
        <div className="pager">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            ‹ Prev
          </button>
          <span>
            Page {page} of {totalPages}
          </span>
          <button disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
            Next ›
          </button>
        </div>
      )}

      {openId !== null && (
        <Viewer
          doc={data?.results.find((d) => d.id === openId) ?? null}
          id={openId}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  );
}
