"""Configuration for the Q3 document classification/extraction pipeline."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Sample KYC pack: Cloud Run uses /app/samples; local default is the assessment zip.
_sample_env = os.environ.get("SAMPLE_INPUT_DIR", "").strip()
if _sample_env:
    DEFAULT_INPUT_DIR = Path(_sample_env)
else:
    DEFAULT_INPUT_DIR = (
        BASE_DIR.parent.parent
        / "Question 1 & 3 (Files to use)"
        / "Question 1 & 3 (Files to use)"
        / "Question 3"
    )
    # Prefer vendored samples/ when present (Docker / portable runs).
    _vendored = BASE_DIR / "samples"
    if _vendored.is_dir() and any(_vendored.iterdir()):
        DEFAULT_INPUT_DIR = _vendored
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"

MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-3.1-flash-lite")
API_KEYS: list[str] = [
    k.strip()
    for k in os.environ.get("GEMINI_API_KEYS", "").split(",")
    if k.strip()
]
if not API_KEYS:
    raise RuntimeError(
        "GEMINI_API_KEYS is empty. Set it in q3_doc_pipeline/.env "
        "(comma-separated list of Gemini API keys)."
    )

# Fields extracted with model-reported confidence below this value are flagged
# for human review. Rationale is documented in report.py / README.md.
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.70"))

# PDF pages are rasterised at this DPI before being sent to the vision model.
PDF_RENDER_DPI = 200

# LLM call settings
MAX_OUTPUT_TOKENS = 4096
KEY_ROTATION_ROUNDS = 2  # total passes over the key pool before giving up

# Supabase auth (same project as Q1). Leave blank / AUTH_DISABLED=true for local anon.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
SUPABASE_ENABLED = bool(SUPABASE_URL and (SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY)) and not AUTH_DISABLED
