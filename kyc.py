"""KYC run logic: process a set of documents for one applicant and consolidate.

A "KYC run" = N uploaded documents -> per-doc classification/extraction ->
consolidated report (applicant identity consensus, document checklist,
cross-document flags). Used by both the Streamlit app and the CLI.
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from config import CONFIDENCE_THRESHOLD
from llm import LLMClient
from pipeline import OTHER_TYPE, process_document
from report import cross_document_consistency, cross_document_table
from schemas import DOC_SCHEMAS

# Fields whose values should agree across documents for the same applicant.
IDENTITY_FIELDS = {
    "applicant_name": [
        "Full Name", "Name", "Name of Life Assured",
        "Policyholder Name", "Proposer Name",
        "Name of Life Assured/Proposed Policyholder",
    ],
    "policy_number": [
        "Policy Number", "Application Number",
        "Application/Proposal Form Number", "Policyholder Name",
    ],
    "date_signed": ["Date"],
}


def process_upload(data: bytes, filename: str, client: LLMClient) -> dict[str, Any]:
    """Process one in-memory upload through the standard pipeline."""
    suffix = Path(filename).suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        result = process_document(tmp_path, client)
        result["file"] = filename  # show the real upload name, not tmp name
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


def _collect(results: list[dict[str, Any]], names: list[str]) -> list[str]:
    vals = []
    for r in results:
        for f in r.get("fields", []):
            if f.get("name") in names and f.get("value"):
                vals.append(str(f["value"]).strip())
    return vals


def _consensus(values: list[str]) -> tuple[str | None, int, int]:
    """Return (consensus_value, agreeing_count, total_count)."""
    if not values:
        return None, 0, 0
    top, n = Counter(values).most_common(1)[0]
    return top, n, len(values)


def build_kyc_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Consolidated KYC view across all documents of one run."""
    found_types = [r["doc_type"] for r in results if r["doc_type"] not in ("ERROR", OTHER_TYPE)]
    missing_types = [t for t in DOC_SCHEMAS if t not in found_types]
    other_docs = [r["file"] for r in results if r["doc_type"] == OTHER_TYPE]

    name_vals = _collect(results, IDENTITY_FIELDS["applicant_name"])
    name, n_name, tot_name = _consensus(name_vals)
    policy_vals = [v for v in _collect(results, IDENTITY_FIELDS["policy_number"]) if v.isdigit()]
    policy, n_policy, tot_policy = _consensus(policy_vals)

    dobs = _collect(results, ["Date of Birth"])
    dob, n_dob, tot_dob = _consensus(dobs)

    all_flags = [
        {
            "file": r["file"],
            "field": f["field"],
            "confidence": f["confidence"],
            "reasons": f.get("reasons") or [],
            "format_ok": f.get("format_ok", True),
            "format_message": f.get("format_message", ""),
        }
        for r in results
        for f in r.get("flagged_fields", [])
    ]
    format_flags = [
        {
            "file": r["file"],
            "field": f.get("name"),
            "value": f.get("value"),
            "rule": f.get("format_rule"),
            "message": f.get("format_message"),
        }
        for r in results
        for f in r.get("fields", [])
        if f.get("value") not in (None, "") and f.get("format_ok") is False
    ]
    cross_flags = cross_document_consistency(results)
    common_fields = cross_document_table(results)

    return {
        "applicant_name": name,
        "applicant_name_agreement": f"{n_name}/{tot_name}" if tot_name else None,
        "policy_number": policy,
        "policy_number_agreement": f"{n_policy}/{tot_policy}" if tot_policy else None,
        "date_of_birth": dob,
        "documents_received": len(results),
        "document_types_identified": found_types,
        "document_types_missing": missing_types,
        "unrecognized_documents": other_docs,
        "low_confidence_flags": all_flags,
        "format_flags": format_flags,
        "cross_document_flags": cross_flags,
        "common_fields": common_fields,
        "kyc_status": (
            "REVIEW REQUIRED"
            if (all_flags or cross_flags or format_flags or missing_types or other_docs)
            else "CLEAN"
        ),
        "threshold": CONFIDENCE_THRESHOLD,
    }


def run_kyc(sources: list[tuple[str, bytes]], client: LLMClient | None = None):
    """Full KYC run over (filename, bytes) pairs. Returns (per_doc_results, summary)."""
    client = client or LLMClient()
    results = []
    for filename, data in sources:
        try:
            results.append(process_upload(data, filename, client))
        except Exception as exc:  # noqa: BLE001 - record and continue
            results.append({
                "file": filename, "doc_type": "ERROR", "is_handwritten": None,
                "fields": [], "flagged_fields": [],
                "schema_issues": [f"pipeline failure: {exc}"],
            })
    return results, build_kyc_summary(results)


def save_run(results: list[dict[str, Any]], summary: dict[str, Any], out_dir: Path) -> None:
    """Persist a KYC run: per-doc JSONs + kyc_summary.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        (out_dir / f"{Path(r['file']).stem}.json").write_text(
            json.dumps(r, indent=2), encoding="utf-8"
        )
    (out_dir / "kyc_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
