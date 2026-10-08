"""Core Q3 pipeline: classify each document, extract fields with confidence."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from google.genai import types

from config import CONFIDENCE_THRESHOLD
from llm import AllKeysExhaustedError, LLMClient
from normalize import normalize_result_fields
from prompts import SCHEMA_BLOCK, SYSTEM_PROMPT, USER_TEMPLATE
from render import render_document
from schemas import DOC_SCHEMAS, HANDWRITTEN_TYPES, fields_for
from validate_format import apply_format_validation

FALLBACK_MODEL = "gemini-3.5-flash"
# Fallback ladder (user constraint: nothing newer than 3.5 as fallback)
FALLBACK_MODELS = ["gemini-3.5-flash"]
OTHER_TYPE = "Other (no extraction schema)"

EXPECTED_FIELD_SETS = {k: set(v) for k, v in DOC_SCHEMAS.items()}


def build_contents(pages_png: list[bytes]) -> list[Any]:
    """One user turn: the prompt followed by every page image (max 4)."""
    prompt = USER_TEMPLATE.format(schema=SCHEMA_BLOCK)
    contents: list[Any] = [prompt]
    for png in pages_png[:4]:  # safety cap on page count
        contents.append(types.Part.from_bytes(data=png, mime_type="image/png"))
    return contents


def parse_model_json(raw: str) -> dict[str, Any]:
    """Parse the model's JSON, tolerating markdown fences or stray prose."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{.*\}", text, re.DOTALL)
        if obj:
            return json.loads(obj.group(0))
        raise


def validate(result: dict[str, Any]) -> list[str]:
    """Return a list of schema-consistency problems (empty == clean)."""
    issues: list[str] = []
    doc_type = result.get("doc_type", "")
    expected = fields_for(doc_type)
    if doc_type == OTHER_TYPE:
        return issues  # free-form extraction, nothing to check against
    if expected is None:
        issues.append(f"unknown doc_type: {doc_type!r}")
        return issues
    got = [f.get("name") for f in result.get("fields", [])]
    missing = sorted(set(expected) - set(got))
    extra = sorted(set(got) - set(expected))
    if missing:
        issues.append(f"missing fields: {missing}")
    if extra:
        issues.append(f"unexpected fields: {extra}")
    for f in result.get("fields", []):
        c = f.get("confidence")
        if not isinstance(c, (int, float)) or not 0.0 <= c <= 1.0:
            issues.append(f"bad confidence for {f.get('name')!r}: {c!r}")
        if f.get("value") is not None and not isinstance(f.get("value"), str):
            issues.append(f"non-string value for {f.get('name')!r}")
    return issues


def process_document(path: Path, client: LLMClient) -> dict[str, Any]:
    """Run classification + extraction for one file; returns the output JSON dict."""
    pages = render_document(path)
    raw: str | None = None
    last_err: Exception | None = None
    try:
        raw = client.generate(build_contents(pages), SYSTEM_PROMPT)
    except AllKeysExhaustedError as exc:
        last_err = exc
    if raw is None:
        # Primary model saturated/unavailable: walk the fallback ladder
        # (gemini-3.5-flash -> gemini-3.1-flash-lite; each has its own quota bucket)
        for fb in FALLBACK_MODELS:
            client.clear_cooldowns()
            try:
                raw = client.generate(build_contents(pages), SYSTEM_PROMPT, model=fb)
                break
            except AllKeysExhaustedError as exc:
                last_err = exc
        if raw is None:
            raise AllKeysExhaustedError(str(last_err))
    parsed = parse_model_json(raw)
    issues = validate(parsed)

    doc_type = parsed.get("doc_type", "Unknown")
    try:
        type_conf = float(parsed.get("classification_confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        type_conf = 0.0
    type_conf = max(0.0, min(1.0, type_conf))
    # If the model omitted classification confidence, infer a conservative default
    # from whether the type is a known schema.
    if type_conf == 0.0:
        type_conf = 0.92 if doc_type in DOC_SCHEMAS else (0.55 if doc_type == OTHER_TYPE else 0.4)

    fields_out = []
    for f in parsed.get("fields", []):
        conf = f.get("confidence", 0.0)
        try:
            conf_f = float(conf)
        except (TypeError, ValueError):
            conf_f = 0.0
        reasons = []
        if conf_f < CONFIDENCE_THRESHOLD:
            reasons.append("low_confidence")
        entry = {
            "name": f.get("name"),
            "value": f.get("value"),
            "confidence": round(conf_f, 2),
            "evidence": f.get("evidence", ""),
            "flagged": bool(reasons),
            "flag_reasons": reasons,
        }
        fields_out.append(entry)

    fields_out = normalize_result_fields(fields_out)
    fields_out = apply_format_validation(fields_out)

    flagged: list[dict[str, Any]] = []
    for entry in fields_out:
        if entry.get("flagged"):
            flagged.append(
                {
                    "field": entry["name"],
                    "confidence": entry["confidence"],
                    "reasons": entry.get("flag_reasons") or [],
                    "format_ok": entry.get("format_ok", True),
                    "format_message": entry.get("format_message", ""),
                }
            )

    return {
        "file": path.name,
        "doc_type": doc_type,
        "classification_confidence": round(type_conf, 2),
        "is_handwritten": parsed.get("is_handwritten", doc_type in HANDWRITTEN_TYPES),
        "fields": fields_out,
        "flagged_fields": flagged,
        "schema_issues": issues,
    }
