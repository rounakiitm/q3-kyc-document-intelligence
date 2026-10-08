"""Q3 KYC API — FastAPI wrapper around the pipeline for the shared frontend.

Job model: POST /kyc/run returns a job_id immediately; the run proceeds in a
background thread; the frontend polls GET /kyc/jobs/{job_id} for progress and
results. GET /kyc/samples lists the provided sample documents.

    uvicorn api:app --port 8003   (from q3_doc_pipeline/)
"""
from __future__ import annotations

import threading
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from config import CONFIDENCE_THRESHOLD, DEFAULT_INPUT_DIR, MODEL_NAME
from kyc import build_kyc_summary, process_upload

app = FastAPI(title="Q3 KYC API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # shared frontend may be served from any local port
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pdf"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME, "threshold": CONFIDENCE_THRESHOLD}


@app.get("/kyc/samples")
def samples() -> dict:
    files = sorted(
        p.name for p in DEFAULT_INPUT_DIR.iterdir()
        if p.suffix.lower() in IMAGE_EXTS
    )
    return {"files": files}


@app.post("/kyc/run")
async def run_kyc(files: list[UploadFile]) -> dict:
    sources = [(f.filename or "upload.png", await f.read()) for f in files]
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "running",
        "progress": 0.0,
        "current": sources[0][0] if sources else "",
        "documents": [],
        "summary": None,
        "error": None,
    }
    with _jobs_lock:
        _jobs[job_id] = job

    def worker() -> None:
        client = _make_client()
        try:
            for i, (fname, data) in enumerate(sources):
                with _jobs_lock:
                    job["current"] = fname
                try:
                    result = process_upload(data, fname, client)
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "file": fname, "doc_type": "ERROR", "is_handwritten": None,
                        "fields": [], "flagged_fields": [],
                        "schema_issues": [f"pipeline failure: {exc}"],
                    }
                job["documents"].append(result)
                with _jobs_lock:
                    job["progress"] = (i + 1) / len(sources)
            job["summary"] = build_kyc_summary(job["documents"])
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = f"{exc}\n{traceback.format_exc()[-400:]}"

    threading.Thread(target=worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/kyc/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with _jobs_lock:
        if job_id not in _jobs:
            return {"status": "unknown"}
        return dict(_jobs[job_id])


def _make_client():
    from llm import LLMClient

    return LLMClient()
