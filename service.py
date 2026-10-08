"""Q3 backend service: auth + session-cached KYC jobs + static frontend.

POST /kyc/sessions              -> {session_id}
POST /kyc/run (files+session)   -> skips content-hashes already in the session
POST /kyc/samples
GET  /kyc/sessions/{id}/docs    -> already-processed docs in this KYC session
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auth import UserDep
from config import (
    API_KEYS,
    DEFAULT_INPUT_DIR,
    MODEL_NAME,
    SUPABASE_ANON_KEY,
    SUPABASE_ENABLED,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from kyc import build_kyc_summary, process_upload
from llm import LLMClient
from schemas import DOC_SCHEMAS

app = FastAPI(title="KYC Document Intelligence", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, dict] = {}
SESSIONS: dict[str, dict] = {}
LOCK = threading.Lock()
_client = LLMClient()


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_session(session_id: str, user_id: str) -> dict:
    with LOCK:
        sess = SESSIONS.get(session_id)
        if sess is None:
            raise HTTPException(404, "kyc session not found — create one via POST /kyc/sessions")
        if sess["user_id"] != user_id:
            raise HTTPException(403, "not your kyc session")
        return sess


@app.get("/")
def root():
    return RedirectResponse(url="/app/")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "keys_in_pool": len(API_KEYS),
        "document_types": len(DOC_SCHEMAS),
        "auth": "supabase" if SUPABASE_ENABLED else "local",
    }


@app.get("/auth/config")
def auth_config():
    return {
        "auth_required": SUPABASE_ENABLED,
        "supabase_url": SUPABASE_URL if SUPABASE_ENABLED else "",
        "supabase_anon_key": SUPABASE_ANON_KEY if SUPABASE_ENABLED else "",
    }


def _supabase_auth_headers() -> dict[str, str]:
    key = SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _proxy_supabase_auth(path: str, body: dict) -> dict:
    if not SUPABASE_ENABLED:
        raise HTTPException(400, "auth not configured")
    url = SUPABASE_URL.rstrip("/") + "/auth/v1/" + path
    try:
        r = httpx.post(url, headers=_supabase_auth_headers(), json=body, timeout=20.0)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"auth upstream failed: {exc}") from exc
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        detail = data.get("error_description") or data.get("msg") or data.get("error") or r.text
        raise HTTPException(r.status_code, detail)
    return data


@app.post("/auth/login")
def auth_login(body: AuthCredentials):
    return _proxy_supabase_auth(
        "token?grant_type=password",
        {"email": body.email, "password": body.password},
    )


@app.post("/auth/signup")
def auth_signup(body: AuthCredentials):
    return _proxy_supabase_auth(
        "signup",
        {"email": body.email, "password": body.password},
    )


@app.get("/auth/me")
def auth_me(user: UserDep):
    return {"id": user.id, "email": user.email, "role": user.role}


@app.post("/kyc/sessions")
def create_kyc_session(user: UserDep):
    sid = uuid.uuid4().hex[:12]
    with LOCK:
        SESSIONS[sid] = {
            "user_id": user.id,
            "docs": {},  # hash -> result dict
            "order": [],  # hashes in first-seen order
        }
    return {"session_id": sid}


@app.get("/kyc/sessions/{session_id}/docs")
def list_session_docs(session_id: str, user: UserDep):
    sess = _get_session(session_id, user.id)
    with LOCK:
        docs = [
            {
                "hash": h,
                "file": sess["docs"][h].get("file"),
                "doc_type": sess["docs"][h].get("doc_type"),
                "cached": True,
            }
            for h in sess["order"]
            if h in sess["docs"]
        ]
    return {"session_id": session_id, "documents": docs, "n_cached": len(docs)}


@app.delete("/kyc/sessions/{session_id}/docs")
def clear_session_docs(session_id: str, user: UserDep):
    sess = _get_session(session_id, user.id)
    with LOCK:
        sess["docs"].clear()
        sess["order"].clear()
    return {"ok": True}


def _start_job(
    sources: list[tuple[str, bytes, str]],
    user_id: str,
    session_id: str,
) -> str:
    """sources: (filename, bytes, content_hash)"""
    if not sources:
        raise HTTPException(400, "no files to process")
    job_id = uuid.uuid4().hex[:12]
    with LOCK:
        JOBS[job_id] = {
            "status": "running",
            "progress": 0.0,
            "current": sources[0][0],
            "results": [],
            "summary": None,
            "error": None,
            "user_id": user_id,
            "session_id": session_id,
            "skipped": [],
            "processed_now": [],
        }
    threading.Thread(target=_run_job, args=(job_id, sources), daemon=True).start()
    return job_id


@app.post("/kyc/run")
async def kyc_run(
    user: UserDep,
    files: list[UploadFile] = File(...),  # noqa: B008
    session_id: str = Form(...),
):
    _get_session(session_id, user.id)
    if not files:
        raise HTTPException(400, "no files uploaded")

    # Deduplicate within this upload batch by content hash (keep first name).
    sources: list[tuple[str, bytes, str]] = []
    seen: set[str] = set()
    for i, f in enumerate(files):
        data = await f.read()
        h = _file_hash(data)
        if h in seen:
            continue
        seen.add(h)
        sources.append((f.filename or f"upload_{i}.png", data, h))

    job_id = _start_job(sources, user.id, session_id)
    return {"job_id": job_id, "n_submitted": len(sources)}


@app.get("/kyc/jobs/{job_id}")
def kyc_job(job_id: str, user: UserDep):
    with LOCK:
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job.get("user_id") and job["user_id"] != user.id and user.role != "anon":
            raise HTTPException(403, "not your job")
        return {
            "status": job["status"],
            "progress": job["progress"],
            "current": job["current"],
            "results": job["results"] if job["status"] == "done" else None,
            "summary": job["summary"],
            "error": job["error"],
            "skipped": job.get("skipped") or [],
            "processed_now": job.get("processed_now") or [],
            "n_session_docs": job.get("n_session_docs") or 0,
        }


@app.post("/kyc/samples")
def load_samples(user: UserDep, session_id: str = Form(...)):
    """Load the 10 assessment documents (session-cached like normal uploads)."""
    _get_session(session_id, user.id)
    if not DEFAULT_INPUT_DIR.exists():
        raise HTTPException(404, f"sample documents not found at {DEFAULT_INPUT_DIR}")
    files = [
        p
        for p in sorted(DEFAULT_INPUT_DIR.iterdir())
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
    ]
    if not files:
        raise HTTPException(404, "sample documents not found")
    sources = []
    for p in files:
        data = p.read_bytes()
        sources.append((p.name, data, _file_hash(data)))
    job_id = _start_job(sources, user.id, session_id)
    return {"job_id": job_id, "n_documents": len(sources)}


def _session_results(sess: dict, new_hashes: set[str]) -> list[dict]:
    """Full session dossier for UI/report — never drop prior docs when a new file is added."""
    out: list[dict] = []
    for h in sess["order"]:
        doc = sess["docs"].get(h)
        if doc is None:
            continue
        row = dict(doc)
        row["content_hash"] = h
        row["cached"] = h not in new_hashes
        out.append(row)
    return out


def _run_job(job_id: str, sources: list[tuple[str, bytes, str]]) -> None:
    with LOCK:
        job = JOBS[job_id]
        session_id = job["session_id"]
        sess = SESSIONS.get(session_id)
    if sess is None:
        with LOCK:
            job["status"] = "error"
            job["error"] = "kyc session disappeared"
        return

    try:
        skipped: list[dict] = []
        processed_now: list[str] = []
        new_hashes: set[str] = set()
        total = len(sources)

        for i, (fname, data, h) in enumerate(sources):
            with LOCK:
                job["current"] = fname
                job["progress"] = i / max(total, 1)
                cached = sess["docs"].get(h)

            if cached is not None:
                # Reuse prior extraction; refresh display filename if user re-uploaded under new name
                with LOCK:
                    cached["file"] = fname
                    cached["content_hash"] = h
                skipped.append({"file": fname, "hash": h, "doc_type": cached.get("doc_type")})
                continue

            with LOCK:
                job["current"] = f"Processing {fname}…"
            try:
                result = process_upload(data, fname, _client)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "file": fname,
                    "doc_type": "ERROR",
                    "classification_confidence": 0.0,
                    "is_handwritten": None,
                    "fields": [],
                    "flagged_fields": [],
                    "schema_issues": [f"pipeline failure: {exc}"],
                }
            result["cached"] = False
            result["content_hash"] = h
            with LOCK:
                sess["docs"][h] = result
                if h not in sess["order"]:
                    sess["order"].append(h)
            new_hashes.add(h)
            processed_now.append(fname)

        with LOCK:
            # Report = entire session cache (prior KYC docs + this run), not only the latest upload.
            results = _session_results(sess, new_hashes)
            job["results"] = results
            job["summary"] = build_kyc_summary(results)
            job["skipped"] = skipped
            job["processed_now"] = processed_now
            job["n_session_docs"] = len(results)
            job["progress"] = 1.0
            job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            job["status"] = "error"
            job["error"] = str(exc)


app.mount(
    "/app",
    StaticFiles(directory=Path(__file__).resolve().parent / "frontend", html=True),
    name="frontend",
)
