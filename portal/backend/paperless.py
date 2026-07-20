"""Thin client over the Paperless-ngx REST API.

Coworkers never see this token; the browser talks only to our FastAPI routes.
"""
from __future__ import annotations

import time

import httpx

from .config import (
    ABSTRACT_FIELD_ID,
    PAPERLESS_API_TOKEN,
    PAPERLESS_API_URL,
    SOURCE_FIELD_ID,
    TRADE_FIELD_ID,
)

_FILE_KINDS = {"preview", "download", "thumb"}


class Paperless:
    def __init__(self):
        self.base = PAPERLESS_API_URL
        self.client = httpx.Client(
            headers={
                "Authorization": f"Token {PAPERLESS_API_TOKEN}",
                "Accept-Encoding": "identity",  # don't let Paperless gzip — we stream raw bytes
            },
            timeout=60,
        )
        self.abstract_fid = ABSTRACT_FIELD_ID
        self.trade_fid = TRADE_FIELD_ID
        self.source_fid = SOURCE_FIELD_ID
        self._tags_by_id: dict[int, str] | None = None
        self._tags_fetched = 0.0
        self._all: list[dict] | None = None
        self._all_fetched = 0.0

    # ---- custom-field helpers ------------------------------------------
    def cf(self, doc: dict, fid: int):
        for item in doc.get("custom_fields", []):
            if item.get("field") == fid:
                return item.get("value")
        return None

    # ---- tag map (cached) ----------------------------------------------
    def tags_by_id(self, ttl: float = 300):
        now = time.time()
        if self._tags_by_id is None or now - self._tags_fetched > ttl:
            r = self.client.get(f"{self.base}/api/tags/", params={"page_size": 200})
            r.raise_for_status()
            self._tags_by_id = {t["id"]: t["name"] for t in r.json()["results"]}
            self._tags_fetched = now
        return self._tags_by_id

    # ---- search --------------------------------------------------------
    def search(self, query: str | None, tag_id: int | None):
        params: dict = {"page_size": 100, "ordering": "-created"}
        if query:
            params["query"] = query
        if tag_id:
            params["tags__id__all"] = tag_id
        out: list[dict] = []
        page = 1
        while True:
            params["page"] = page
            r = self.client.get(f"{self.base}/api/documents/", params=params)
            r.raise_for_status()
            data = r.json()
            out.extend(data["results"])
            if not data.get("next"):
                break
            page += 1
            if page > 50:  # safety cap (~5000 docs)
                break
        return out

    def all_docs(self, ttl: float = 300):
        """Cached unfiltered list, used for facets."""
        now = time.time()
        if self._all is None or now - self._all_fetched > ttl:
            self._all = self.search(None, None)
            self._all_fetched = now
        return self._all

    def get(self, doc_id: int) -> dict:
        r = self.client.get(f"{self.base}/api/documents/{doc_id}/")
        r.raise_for_status()
        return r.json()

    def stream(self, doc_id: int, kind: str) -> httpx.Response:
        if kind not in _FILE_KINDS:
            raise ValueError(f"bad kind: {kind}")
        req = self.client.build_request(
            "GET", f"{self.base}/api/documents/{doc_id}/{kind}/"
        )
        resp = self.client.send(req, stream=True)
        if resp.status_code >= 400:
            resp.read()
            resp.close()
            resp.raise_for_status()
        return resp

    # ---- frontend shape ------------------------------------------------
    def serialize(self, doc: dict) -> dict:
        names = self.tags_by_id()
        tag_ids = doc.get("tags", []) or []
        return {
            "id": doc["id"],
            "title": doc.get("title", "") or "",
            "abstract": self.cf(doc, self.abstract_fid) or "",
            "trade": self.cf(doc, self.trade_fid) or "",
            "source": self.cf(doc, self.source_fid) or "",
            "tags": [{"id": i, "name": names.get(i, str(i))} for i in tag_ids],
            "created": doc.get("created"),
        }


# Module-level singleton for the app.
P = Paperless()
