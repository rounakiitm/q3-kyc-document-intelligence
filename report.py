"""Flagging report + processing notes generation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import CONFIDENCE_THRESHOLD
from pipeline import OTHER_TYPE
from schemas import DOC_SCHEMAS, HANDWRITTEN_TYPES, fields_for

THRESHOLD_RATIONALE = (
    f"Threshold = {CONFIDENCE_THRESHOLD:.2f}. The pipeline is downstream of a human "
    "reviewer: anything at or above this level was read consistently with its "
    "surrounding context (evidence snippet available), while scores below it mean the "
    "handwriting required real interpretation - exactly where a silent misread of an "
    "account number, IFSC or date would be costly. For graded high-value handwritten "
    "fields (IFSC, TIN, account numbers, dates, places) a false extraction is worse "
    "than a flagged one, so the threshold deliberately favours recall of errors over "
    "minimising reviewer workload. Handwritten fields sit under the same threshold as "
    "printed ones because the model's self-assessed confidence already prices in "
    "legibility; a confidently-read digit on a form is as trustworthy as printed text."
)

NOTE_HANDWRITTEN = """## How handwritten text was handled differently from printed text

**Printed identity proofs** (Aadhaar, PAN, Driving Licence, Passport) use fixed, \
machine-printed layouts. The pipeline reads them at full resolution with no special \
handling, and model confidence on these documents was consistently high, so they are \
taken as-is.

**Handwritten insurance forms** (NACH/ECS mandate, FATCA annexure, benefit \
illustration, moral hazard questionnaire, multiple-policies consent, suitability \
profiler) received three deliberate accommodations:

1. **Higher effective resolution** - scans are downscaled to a 2000px cap, and PDFs \
are rasterised at 200 DPI, chosen so that box-by-box handwritten digits (the bank \
account number and IFSC on the NACH form) stay legible rather than being smoothed away.
2. **Character-by-character prompting** - the extraction prompt instructs the model to \
read handwritten codes digit by digit and to return `null` with confidence 0.0 when a \
value is genuinely unreadable, instead of guessing. Codes are requested without spaces \
so stray ink gaps do not corrupt the value.
3. **Per-field confidence + flagging** - every field carries a self-assessed confidence \
score under a fixed rubric (printed: 0.95+, legible handwriting: 0.80-0.95, ambiguous \
handwriting: 0.50-0.80, barely legible: <0.50). Fields below the {threshold:.2f} \
threshold are flagged for human review with their evidence snippet, because a silently \
misread account number is far more expensive downstream than a flagged review queue.

**Failure cases observed**: signatures and the dates written as "26|04|2026" with \
pipe-like strokes required interpretation (the separator is a slashed handwriting \
style, not the digit 1); on the NACH mandate the IFSC code and account number are \
written in small boxes that force a character-by-character read and are the most \
likely fields for any OCR pipeline to err on; cross-document consistency (same \
proposer "Ashok", same policy number 1500137601025 across six forms) provides a free \
sanity check, and any form disagreeing with the consensus would itself be flagged.
"""


def cross_document_consistency(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag mismatches on shared identity fields across the KYC pack.

    Covers name, DOB, father name, PAN/TIN, policy/application numbers,
    signed dates, and place — not only 'Date'.
    """
    from crosscheck import cross_document_common_fields

    return cross_document_common_fields(results)["flags"]


def cross_document_table(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agreement rows for the UI (common-field consensus table)."""
    from crosscheck import cross_document_common_fields

    return cross_document_common_fields(results)["common_fields"]


def make_flagging_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    flagged_docs = []
    for r in results:
        expected = fields_for(r["doc_type"])
        missing = sorted(set(expected or []) - {f["name"] for f in r["fields"] if f["value"] not in (None, "")})
        doc_flagged = {
            "file": r["file"],
            "doc_type": r["doc_type"],
            "flagged_fields": r["flagged_fields"],
            "extraction_gaps": missing,
            "schema_issues": r["schema_issues"],
        }
        if (doc_flagged["flagged_fields"] or doc_flagged["extraction_gaps"]
                or r["schema_issues"] or r["doc_type"] == OTHER_TYPE):
            flagged_docs.append(doc_flagged)
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
    return {
        "threshold": CONFIDENCE_THRESHOLD,
        "threshold_rationale": THRESHOLD_RATIONALE,
        "total_documents": len(results),
        "documents_flagged": len(flagged_docs),
        "format_flags": format_flags,
        "cross_document_flags": cross_document_consistency(results),
        "common_fields": cross_document_table(results),
        "flagged": flagged_docs,
    }


def write_reports(results: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = make_flagging_report(results)
    (out_dir / "flagging_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    lines = [
        "# Q3 Flagging Report",
        "",
        f"**Threshold:** {CONFIDENCE_THRESHOLD:.2f} per-field confidence "
        f"({report['documents_flagged']} of {report['total_documents']} documents flagged)",
        "",
        "## Threshold rationale",
        "",
        THRESHOLD_RATIONALE,
        "",
    ]
    if report["flagged"]:
        lines += ["## Flagged items", ""]
        for d in report["flagged"]:
            lines.append(f"### `{d['file']}` — {d['doc_type']}")
            if d["flagged_fields"]:
                for f in d["flagged_fields"]:
                    lines.append(f"- Field **{f['field']}** confidence {f['confidence']:.2f} → human review")
            else:
                lines.append("- No low-confidence fields")
            if d["extraction_gaps"]:
                lines.append(f"- Extraction gaps (value empty): {d['extraction_gaps']}")
            if d["schema_issues"]:
                lines.append(f"- Schema issues: {d['schema_issues']}")
            lines.append("")
    else:
        lines += ["## Flagged items", "", "None - every field cleared the threshold.", ""]

    if report.get("cross_document_flags"):
        lines += ["## Cross-document consistency flags", ""]
        for cflag in report["cross_document_flags"]:
            lines.append(f"- **`{cflag['file']}`**: {cflag['detail']}")
        lines.append("")

    lines += [
        "## Handwritten vs printed handling",
        "",
        NOTE_HANDWRITTEN.format(threshold=CONFIDENCE_THRESHOLD),
        "",
        "## Extraction schemas used",
        "",
    ]
    for dtype, flds in DOC_SCHEMAS.items():
        lines.append(f"- **{dtype}**: {', '.join(flds)}")
    (out_dir / "flagging_report.md").write_text("\n".join(lines), encoding="utf-8")
