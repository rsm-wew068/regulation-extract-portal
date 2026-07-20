# Deploying the Brookfield Document Portal

Architecture (live-proxy): **Caddy (HTTPS)** → React SPA + `/api/*` → **FastAPI** → **Paperless** (private).
Coworkers reach only `https://<DOMAIN>`; Paperless has no public port.

## Prerequisites
- A VPS (e.g. DigitalOcean/Hetzner, ≥2 GB) with Docker + the `compose` plugin installed.
- A domain (e.g. `docs.yourcompany.com`) with an **A record** pointing at the VPS IP.

## 1. On your Mac — prepare artifacts
```bash
cd regulation-extract/portal

# Build the frontend (produces frontend/dist/)
npm --prefix frontend install
npm --prefix frontend run build

# Export everything from your local Paperless (docs + DB + custom fields)
docker compose --project-directory ../paperless-ngx exec webserver document_exporter ../export
```
Then copy the repo (including `frontend/dist/` and `paperless-ngx/export/`) to the server, e.g.:
```bash
rsync -av --exclude node_modules --exclude .venv \
  ./ user@<VPS>:/opt/regulation-extract/
```

## 2. On the server — configure
```bash
cd /opt/regulation-extract/portal
cp .env.prod.example .env.prod
# edit .env.prod: set DOMAIN, POSTGRES_PASSWORD, PAPERLESS_SECRET_KEY
#   (generate secrets with: openssl rand -hex 32)
```

## 3. On the server — start the stack
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```
Paperless runs first-time init (migrations). Wait until `webserver` is healthy:
```bash
docker compose -f docker-compose.prod.yml ps
```

## 4. On the server — create the admin + read-only API user
```bash
# Admin (if migrating by token instead of exporter), then a read-only user for the portal:
docker compose -f docker-compose.prod.yml exec webserver python3 manage.py createsuperuser
# In the Paperless UI (http://<VPS>:8000 via a temporary port, or `docker compose ... exec`):
#   My Profile -> Administration -> Users -> create a read-only user
#   then generate that user's Auth Token and paste it into .env.prod as PAPERLESS_API_TOKEN
```
(If you used `document_exporter` in step 1, your local admin/custom fields/docs are already restored — just create the read-only token.)

Verify the custom-field IDs on the server and set them in `.env.prod`:
```bash
docker compose -f docker-compose.prod.yml exec webserver \
  sh -c 'curl -s -H "Authorization: Token $PAPERLESS_API_TOKEN" http://webserver:8000/api/custom_fields/'
# set ABSTRACT_FIELD_ID / TRADE_FIELD_ID to the returned ids, then:
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d backend
```

## 5. Enrich on the server (optional: upgrade abstracts to AI quality)
```bash
docker compose -f docker-compose.prod.yml run --rm --env-file .env.prod \
  backend python /app/../scripts/enrich.py --force
# (or run scripts/enrich.py locally with LLM_PROVIDER=anthropic + LLM_API_KEY set, then re-export)
```

## 6. Verify (end-to-end)
- Open `https://<DOMAIN>` → search, filter **Cabinetry**, open a PDF.
- Confirm `<VPS-IP>:8000` is **not** reachable (Paperless is private).
- `curl https://<DOMAIN>/api/health` → `{"ok":true}`.

## Notes
- **LLM abstracts**: set `LLM_PROVIDER` + `LLM_API_KEY` in the environment and run `enrich.py --force` to replace excerpt-based abstracts with Claude/OpenAI summaries.
- **Portal auth (optional)**: add `basic_auth` to the Caddyfile if the URL must not be fully public.
- **Backups**: periodically run `document_exporter ../export` on the server.
