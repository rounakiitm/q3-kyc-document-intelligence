# KYC Document Intelligence (Q3)

**Prod demo URL:** https://q3-kyc-frontend.vercel.app  
**Prod API URL:** https://q3-kyc-pipeline-yp4xrztlaq-el.a.run.app

Classifies KYC / insurance onboarding documents (Aadhaar, PAN, passport, NACH,
FATCA, etc.), extracts required fields with per-field confidence, normalizes
values, checks formats, and builds a cross-document consistency report.

## Prod demo URLs

| | URL |
|---|---|
| **Prod demo (UI — Vercel)** | https://q3-kyc-frontend.vercel.app |
| **Prod API (Cloud Run)** | https://q3-kyc-pipeline-yp4xrztlaq-el.a.run.app |
| **API health** | https://q3-kyc-pipeline-yp4xrztlaq-el.a.run.app/health |
| **Source** | https://github.com/rounakiitm/q3-kyc-document-intelligence |

Split deploy: static frontend on **Vercel**, FastAPI backend on **Cloud Run**.
The UI calls the API via `window.__KYC_API__` in `frontend/config.js`.

## Authentication

**Production uses Supabase Auth** (same project as Q1) — not a custom user DB.

| Mode | Behaviour |
|---|---|
| **Prod (Vercel + Cloud Run)** | SPA shows sign-in / sign-up. Login/signup are proxied by FastAPI to Supabase Auth. Access token is kept in `localStorage` and sent as `Authorization: Bearer <jwt>` on KYC/session calls. Backend validates JWT (`SUPABASE_JWT_SECRET` HS256, or Supabase `/auth/v1/user`). KYC session cache is scoped to that `user_id`. |
| **Local with Supabase env** | Same gate as prod; point the SPA at local uvicorn (empty `__KYC_API__`). |
| **`AUTH_DISABLED=true` or no Supabase env** | Auth gate off; fixed anonymous user — useful for offline demos / tests. |

There is no separate manual password file or admin login; credentials are managed
entirely by Supabase.

Click **Load sample documents** for the assessment pack, or upload your own
images/PDFs, then **Run KYC**.

The UI shows:

1. **Classification table** — file → predicted type + confidence  
2. **Normalized field tables** — value / confidence / format / evidence  
3. **Cross-document common fields** — name, DOB, PAN, policy, etc.  
4. **KYC report** — checklist, flags, downloadable JSON  

Same-session uploads **append** to the dossier; already-processed files are
skipped by content hash. Unrelated docs (e.g. a resume) do not wipe prior results.

## What it does

```
Image / PDF
    → render pages (Pillow / pypdfium2)
    → one Gemini vision call per new document
         ├─ doc_type + classification confidence
         ├─ field values + per-field confidence
         └─ evidence snippets
    → normalize (dates, PAN, Aadhaar, IFSC, …)
    → format rules (PAN pattern, etc.)
    → session cache by SHA-256
    → cross-document consensus + flagging report
```

Pipeline is **document-type driven**: new applicants use the same path
(upload → classify → extract → flag → consolidate).

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Vanilla HTML / CSS / JS on **Vercel** | Static SPA; talks to Cloud Run via `config.js` (`window.__KYC_API__`) |
| API | **FastAPI** + **Uvicorn** on **Cloud Run** | Auth, session cache, async KYC jobs |
| Vision / LLM | **Google Gemini** (`google-genai`) | Classify + extract in one structured JSON call |
| PDF / images | **pypdfium2** + **Pillow** | Rasterize PDFs; normalize images for vision |
| Auth | **Supabase Auth** (proxy + JWT via **PyJWT** / httpx) | Same login project as Q1 |
| Validation | Custom normalize + format rules | PAN / Aadhaar / dates / IFSC consistency |
| Cross-check | Custom consensus helpers | Majority agreement across docs |
| Samples | Bundled under `samples/` | Cloud Run “Load samples” works without the assessment zip |
| Secrets | GCP Secret Manager (`GEMINI_API_KEYS`) | Keys not baked into the image |
| Tests | **pytest** | Offline normalize / format / schema tests |

## Run locally

```bash
pip install -r requirements.txt
cp ../q1_excel_agent/.env .env   # or set GEMINI_API_KEYS + SUPABASE_*
# AUTH_DISABLED=true for anon local use
uvicorn service:app --host 127.0.0.1 --port 8003
# UI: http://localhost:8003/app
```

Leave `frontend/config.js` with an empty `__KYC_API__` for same-origin local use.
Vercel deploys overwrite it with the Cloud Run URL.

### Batch CLI (same engine)

```bash
python run_pipeline.py            # uses samples/ or assessment zip path
python run_pipeline.py --force
```

Outputs land in `output/` (`<doc>.json`, `flagging_report.json` / `.md`).

### Redeploy

```bash
# Backend (from WSL): bash scripts/deploy_cloudrun.sh
# Frontend:           .\scripts\deploy_vercel.ps1
```

## Confidence & flagging

Threshold **0.70**. Rubric given to the model: printed ~0.95+, legible
handwriting 0.80–0.95, ambiguous 0.50–0.80, barely legible &lt;0.50. Unreadable
fields return `null` at 0.0 instead of guessing.

## Main API

```
GET  /health
POST /auth/login | /auth/signup
GET  /auth/me
POST /kyc/sessions
POST /kyc/run              # multipart files + session_id
POST /kyc/samples
GET  /kyc/jobs/{id}
GET  /kyc/sessions/{id}/docs
DELETE /kyc/sessions/{id}/docs
```

## Tests

```bash
python -m pytest tests -q
```
