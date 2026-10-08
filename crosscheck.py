"""Cross-document consistency on shared identity / KYC fields."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

# Logical identity buckets → possible field names across document types
COMMON_FIELD_GROUPS: dict[str, list[str]] = {
    "applicant_name": [
        "Full Name",
        "Name",
        "Name of Life Assured",
        "Policyholder Name",
        "Proposer Name",
        "Name of Life Assured/Proposed Policyholder",
    ],
    "date_of_birth": ["Date of Birth"],
    "father_name": ["Father's Name"],
    "pan_tin": ["PAN Number", "TIN / PAN"],
    "policy_or_application": [
        "Policy Number",
        "Application Number",
        "Application/Proposal Form Number",
    ],
    "signed_date": ["Date"],
    "place": ["Place"],
}


def _canon_name(text: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", "", (text or "").casefold())
    return re.sub(r"\s+", " ", t).strip()


def _canon_value(group: str, text: str) -> str:
    if group == "applicant_name" or group == "father_name":
        return _canon_name(text)
    if group in {"pan_tin"}:
        return re.sub(r"[^A-Z0-9]", "", text.upper())
    if group in {"policy_or_application"}:
        return re.sub(r"\D", "", text)
    if group in {"date_of_birth", "signed_date"}:
        return text.strip()
    if group == "place":
        return _canon_name(text)
    return (text or "").strip().casefold()


def collect_group_values(
    results: list[dict[str, Any]], group: str, names: list[str]
) -> list[tuple[str, str, str, float]]:
    """Return list of (file, field_name, display_value, confidence)."""
    out = []
    name_set = set(names)
    for r in results:
        for f in r.get("fields", []):
            if f.get("name") in name_set and f.get("value") not in (None, ""):
                out.append(
                    (
                        r.get("file", "?"),
                        str(f.get("name")),
                        str(f.get("value")),
                        float(f.get("confidence") or 0),
                    )
                )
    return out


def cross_document_common_fields(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build agreement table + flags for common fields across the KYC pack."""
    groups_out = []
    flags: list[dict[str, Any]] = []

    for group, names in COMMON_FIELD_GROUPS.items():
        rows = collect_group_values(results, group, names)
        if not rows:
            continue

        canon_counts: Counter[str] = Counter()
        display_for: dict[str, str] = {}
        for _file, _fname, val, _c in rows:
            key = _canon_value(group, val)
            if not key:
                continue
            canon_counts[key] += 1
            display_for.setdefault(key, val)

        if not canon_counts:
            continue

        consensus_key, n_agree = canon_counts.most_common(1)[0]
        consensus_display = display_for[consensus_key]
        total = sum(canon_counts.values())
        distinct = len(canon_counts)

        sightings = [
            {
                "file": file,
                "field": fname,
                "value": val,
                "confidence": conf,
                "matches_consensus": _canon_value(group, val) == consensus_key,
            }
            for file, fname, val, conf in rows
        ]

        groups_out.append(
            {
                "group": group,
                "label": group.replace("_", " ").title(),
                "consensus": consensus_display,
                "agreement": f"{n_agree}/{total}",
                "distinct_values": distinct,
                "status": "OK" if distinct == 1 else "MISMATCH",
                "sightings": sightings,
            }
        )

        if distinct > 1 and total >= 2:
            for s in sightings:
                if not s["matches_consensus"]:
                    flags.append(
                        {
                            "file": s["file"],
                            "type": "cross_document_mismatch",
                            "field": s["field"],
                            "group": group,
                            "detail": (
                                f"{s['field']} = {s['value']!r} disagrees with "
                                f"cross-document consensus {consensus_display!r} "
                                f"({n_agree}/{total} agree)"
                            ),
                        }
                    )

    return {"common_fields": groups_out, "flags": flags}
