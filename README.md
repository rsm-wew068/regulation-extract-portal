# Document Portal

A read-only search portal over [Paperless-ngx](https://docs.paperless-ngx.com).
Coworkers search and read bid / specification documents by **project**, **trade**,
and **source** (text vs. images) — and open them inline — without ever touching
Paperless. A shared-passphrase login gates access so only coworkers get in.

## Architecture

```
Browser ──> React SPA (Vercel) ──/api──> FastAPI proxy (backend host) ──> Paperless (private)
```

- **Frontend** — React + Vite (`portal/frontend`). Deploy on Vercel.
- **Backend** — FastAPI (`portal/backend`). Proxies Paperless's REST API; holds the
  Paperless API token and the portal password. Paperless has no public port.
- **Paperless-ngx** (`paperless-ngx/`) — the document store, run via Docker.
- **Scripts** (`portal/scripts/`) — `enrich.py` (Abstract + Trade),
  `classify.py` (Source: Text / Mixed / Images).

## Repo layout

```
portal/frontend/            React + Vite SPA (search UI)
portal/backend/             FastAPI proxy + auth
portal/scripts/             enrichment + classification jobs
portal/docker-compose.prod.yml, Caddyfile   backend-host deployment
paperless-ngx/              Paperless-ngx Docker stack
```

## Local development

Run both dev servers from the repo root (uses the project `.venv`):
```
bash portal/dev.sh
```
- frontend: http://localhost:5173
- backend:  http://localhost:8001
- Paperless must already be running (`paperless-ngx/`) on :8000.

Copy `portal/.env.example` → `portal/.env` and fill in: the Paperless URL + API
token, the custom-field IDs (`ABSTRACT_FIELD_ID`, `TRADE_FIELD_ID`,
`SOURCE_FIELD_ID`), `CORS_ORIGINS`, and `PORTAL_PASSWORD` / `PORTAL_SECRET`.

Populate document metadata:
```
.venv/bin/python portal/scripts/enrich.py     # Abstract + Trade
.venv/bin/python portal/scripts/classify.py   # Source (Text/Mixed/Images)
```
Both are idempotent — safe to re-run when new documents land.

## Auth

Shared passphrase. Set `PORTAL_PASSWORD` (and a random `PORTAL_SECRET`) on the
backend. A coworker enters the password once; the backend returns an HMAC-signed
bearer token required on every `/api` route. Thumbnails and downloads pass the
token via `?token=` (they can't send an `Authorization` header).

## Deploy

### Frontend → Vercel
1. Connect the GitHub repo to Vercel.
2. Set **Root Directory = `portal/frontend`** (Vercel auto-detects Vite).
3. In `portal/frontend/vercel.json`, replace `REPLACE-WITH-BACKEND-HOST` with the
   backend host URL (below) and push. Vercel proxies `/api/*` there.

### Backend + Paperless → VPS
Prerequisites: a VPS (DigitalOcean/Hetzner, ≥2 GB) with Docker + the `compose`
plugin; a domain with an **A record** pointing at the VPS.

```bash
# 1. On your Mac — build the frontend and export your local Paperless data
npm --prefix portal/frontend install && npm --prefix portal/frontend run build
docker compose --project-directory paperless-ngx exec webserver document_exporter ../export

# 2. Copy the repo to the server
rsync -av --exclude node_modules --exclude .venv ./ user@<VPS>:/opt/regulation-extract/

# 3. On the server — configure and start
cd /opt/regulation-extract/portal
cp .env.prod.example .env.prod          # set DOMAIN, POSTGRES_PASSWORD, PAPERLESS_SECRET_KEY,
                                        # PAPERLESS_API_TOKEN, PORTAL_PASSWORD, PORTAL_SECRET
                                        # (secrets via: openssl rand -hex 32)
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps   # wait until webserver is healthy

# 4. Create a read-only Paperless user + token (for the backend), then set
#    PAPERLESS_API_TOKEN in .env.prod and restart the backend.
#    (If you imported via document_exporter in step 1, your docs/tags/custom
#     fields are already restored — just create the token.)

# 5. Populate Abstract/Trade/Source on the server
docker compose -f docker-compose.prod.yml run --rm --env-file .env.prod \
  backend sh -lc 'cd /app/.. && python scripts/enrich.py && python scripts/classify.py'
```

### Verify
- Open `https://<DOMAIN>` → log in, search, filter by Trade/Source, open a document.
- `https://<DOMAIN>:8000` (Paperless) should **not** be reachable.
- `curl https://<DOMAIN>/api/health` → `{"ok":true}`.

## Notes
- **Abstracts** are excerpts of each document's extracted text (kept short —
  Paperless string fields cap at 128 chars). `enrich.py` supports Claude/OpenAI
  if you ever want AI-phrased summaries (`LLM_PROVIDER` + `LLM_API_KEY`).
- **Backups**: periodically run `document_exporter ../export` on the server.
