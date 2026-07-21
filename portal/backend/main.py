"""FastAPI proxy in front of Paperless-ngx.

All routes are read-only and add no coworker-facing auth (guard at the reverse
proxy if needed). The browser never sees the Paperless token or URL.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import CORS_ORIGINS, PORTAL_PASSWORD, PORTAL_SECRET, SUMMARIES_FILE
from .paperless import P

app = FastAPI(title="Document Portal API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---- auth: shared-passphrase gate ------------------------------------
def _sign(body: str) -> str:
    return hmac.new(PORTAL_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    body = base64.urlsafe_b64encode(json.dumps({"k": "portal"}).encode()).decode()
    return f"{body}.{_sign(body)}"


def check_token(token: str) -> bool:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return False
    return hmac.compare_digest(sig, _sign(body))


_PUBLIC = {"/api/login", "/api/health"}


@app.middleware("http")
async def require_auth(request, call_next):
    path = request.url.path
    if path in _PUBLIC or not path.startswith("/api/"):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    tok = auth[7:].strip() if auth.startswith("Bearer ") else (request.query_params.get("token") or "")
    if tok and check_token(tok):
        return await call_next(request)
    return JSONResponse({"detail": "unauthorized"}, status_code=401)


@app.post("/api/login")
def login(payload: dict = Body(...)):
    if not PORTAL_PASSWORD or payload.get("password") != PORTAL_PASSWORD:
        raise HTTPException(401, "wrong password")
    return {"token": make_token()}


_FILE_KINDS = {"preview", "download", "thumb"}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/facets")
def facets():
    """Project tags + the trade values present in the corpus."""
    docs = P.all_docs()
    names = P.tags_by_id()
    projects = [
        {"id": tid, "name": name}
        for tid, name in names.items()
        if name.startswith("Brookfield")
    ]
    trades = sorted({P.cf(d, P.trade_fid) for d in docs if P.cf(d, P.trade_fid)})
    sources = sorted({P.cf(d, P.source_fid) for d in docs if P.cf(d, P.source_fid)})
    return {"projects": projects, "trades": trades, "sources": sources}


@app.get("/api/documents")
def documents(
    q: str | None = Query(None),
    tag_id: int | None = None,
    trade: str | None = None,
    source: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    docs = P.search(q, tag_id)
    if trade:
        docs = [d for d in docs if P.cf(d, P.trade_fid) == trade]
    if source:
        docs = [d for d in docs if P.cf(d, P.source_fid) == source]
    total = len(docs)
    start = (page - 1) * page_size
    page_docs = docs[start : start + page_size]
    return {
        "results": [P.serialize(d) for d in page_docs],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/documents/{doc_id}")
def document(doc_id: int):
    doc = P.get(doc_id)
    out = P.serialize(doc)
    out["content"] = doc.get("content") or ""
    out["summary"] = _summaries().get(str(doc_id), "")
    return out


# Rich summaries from summaries.json (reloads when the file changes).
_sm_cache = {"mtime": 0.0, "data": {}}


def _summaries():
    try:
        m = SUMMARIES_FILE.stat().st_mtime
    except OSError:
        return _sm_cache["data"]
    if m != _sm_cache["mtime"]:
        try:
            _sm_cache["data"] = json.loads(SUMMARIES_FILE.read_text())
        except Exception:
            _sm_cache["data"] = {}
        _sm_cache["mtime"] = m
    return _sm_cache["data"]


@app.get("/api/documents/{doc_id}/{kind}")
def doc_file(doc_id: int, kind: str):
    if kind not in _FILE_KINDS:
        raise HTTPException(400, "kind must be one of: preview, download, thumb")
    resp = P.stream(doc_id, kind)
    try:
        body = resp.read()  # full bytes, auto-decompressed by httpx
    finally:
        resp.close()
    headers = {"content-type": resp.headers.get("content-type", "application/octet-stream")}
    cd = resp.headers.get("content-disposition")
    if cd:
        headers["content-disposition"] = cd
    return Response(content=body, headers=headers)
