# Railway deployment

Moves the **whole stack** off the Mac/Cloudflare tunnel onto Railway. Result:
Vercel frontend → Railway backend (permanent URL) → Railway Paperless, all on
Railway's private network. No Mac, no tunnel, no changing URLs.

```
Browser ──> React SPA (Vercel) ──/api──> FastAPI backend (Railway, public)
                                              │  private network
                                              ▼
                                         Paperless (Railway, PRIVATE)
                                              ├── Postgres (Railway plugin)
                                              └── Redis    (Railway plugin)
```

Paperless is **never** given a public domain — only `backend` reaches it over
Railway's internal network. Coworkers hit only the backend's `/api`.

---

## Services to create (in one Railway project)

Create a new Railway project, then add these four services.

### 1. Postgres  — `Add → Database → PostgreSQL`
Nothing to configure. Exposes `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`.

### 2. Redis — `Add → Database → Redis`
Nothing to configure. Exposes `REDIS_URL`.

### 3. Paperless — `Add → Docker Image` → `ghcr.io/paperless-ngx/paperless-ngx:latest`
- **Attach a Volume** (`Add → Volume`) mounted at **`/data`**. This one volume
  holds all persistent Paperless state (see the DATA_DIR/MEDIA_ROOT vars below),
  so the container's own `/usr/src/paperless` code dir is never shadowed.
  **Size: start at ~10 GB** (current data is 2.6 GB — leaves room to grow). This
  volume is permanent: it survives deploys, restarts, and redeploys. You can
  increase the size later. (No automated backup is configured — the same
  `document_exporter` used for migration can be scheduled off-Railway later if
  point-in-time recovery is ever wanted.)
- **Do NOT** add a public domain. Keep it private.
- Variables (use Railway variable references for the DB/Redis ones):

  ```
  PAPERLESS_DBHOST        = ${{Postgres.PGHOST}}
  PAPERLESS_DBPORT        = ${{Postgres.PGPORT}}
  PAPERLESS_DBNAME        = ${{Postgres.PGDATABASE}}
  PAPERLESS_DBUSER        = ${{Postgres.PGUSER}}
  PAPERLESS_DBPASS        = ${{Postgres.PGPASSWORD}}
  PAPERLESS_REDIS         = ${{Redis.REDIS_URL}}
  PAPERLESS_SECRET_KEY    = <long random string>
  PAPERLESS_URL           = http://localhost         # internal only; never public
  PAPERLESS_PORT          = 8000
  PAPERLESS_DATA_DIR      = /data/data
  PAPERLESS_MEDIA_ROOT    = /data/media
  PAPERLESS_CONSUMPTION_DIR = /data/consume
  PAPERLESS_OCR_MODE      = skip_noarchive
  PAPERLESS_TIME_ZONE     = America/Los_Angeles
  PAPERLESS_CONSUMER_POLLING = 10
  ```

  Then create the admin user once (Railway shell on the Paperless service):
  ```
  python manage.py createsuperuser
  ```
  and generate an API token in Paperless (Django admin → Auth Tokens) for the
  backend below.

### 4. Backend — `Add → GitHub Repo` → this repo
- **Root directory**: `portal`  (so the Dockerfile's `COPY backend/` resolves).
  Railway will use `portal/backend/Dockerfile`. If Railway defaults to the wrong
  Dockerfile, set **Dockerfile path** = `backend/Dockerfile`.
- Generate a **public domain** (`Settings → Networking → Generate Domain`). This
  is the permanent URL Vercel points at.
- Variables:

  ```
  PAPERLESS_API_URL  = http://${{Paperless.RAILWAY_PRIVATE_DOMAIN}}:8000
  PAPERLESS_API_TOKEN = <token from step 3>
  ABSTRACT_FIELD_ID  = 1
  TRADE_FIELD_ID     = 2
  SOURCE_FIELD_ID    = 3             # REQUIRED by config.py — don't omit
  CORS_ORIGINS       = https://<your-vercel-domain>
  PORTAL_PASSWORD    = <FRESH shared passphrase — not the dev "abcabinets2026">
  PORTAL_SECRET      = <FRESH long random string — not the dev "dev-secret-change-me">
  ```

  The backend binds Railway's injected `$PORT` automatically (see
  `portal/backend/Dockerfile`).

---

## Point Vercel at the backend

Edit `portal/frontend/vercel.json` — replace the Cloudflare tunnel host with the
backend's Railway domain, then redeploy the frontend:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://<backend>.up.railway.app/api/:path*" }
  ]
}
```

This is the last URL you ever have to change.

---

## One-time data migration (302 documents)

Paperless has a built-in exporter/importer that carries documents **and** all
metadata (tags, custom fields, correspondents) across.

Current data on the Mac: **media ≈ 2.6 GB**, pgdata ≈ 85 MB, index ≈ 12 MB. The
exporter bundles media + metadata into one dir; ~2.6 GB moves via Vercel Blob in
a few minutes each way. (Ongoing growth lives on the Railway Volume — this
transfer is one-time.)

**1. Export locally** (Mac, with the current stack running):
```
cd paperless-ngx
docker compose exec webserver document_exporter ../export
tar czf /tmp/pl-export.tgz -C export .
```

**2. Get the tarball onto the Railway volume via Vercel Blob** (private by
default — you control deletion; preferred over public temp hosts for confidential
docs). Railway has no scp, so we upload once and `curl` it down:
```
# Mac
vercel blob put /tmp/pl-export.tgz          # prints a private URL
```
```
# Railway shell on the Paperless service
mkdir -p /data/import && cd /data/import
curl -L "<blob-url>" -o pl-export.tgz && tar xzf pl-export.tgz
```
Delete the blob (`vercel blob del <url>`) once the import below succeeds.

**3. Import** (Railway shell on the Paperless service):
```
python manage.py document_importer /data/import
python manage.py document_index reindex
```

**4. Verify** the count matches (302) in the backend: hit
`https://<backend>.up.railway.app/api/health` and load the portal.

> We'll do steps 2–3 together interactively once the services are up — the
> file-transfer step needs live Railway access and a fetchable URL.

---

## Notes / gotchas
- `summaries.json` ships in the repo (`portal/summaries.json`) and is read from
  the backend image — no volume needed for it. Rebuild/redeploy the backend when
  it changes.
- The enrichment/classification scripts (`portal/scripts/`) can be run later as a
  one-off against the Railway Paperless once documents are imported.
- Cost: roughly ~$5–15/mo depending on Paperless memory + volume size.
