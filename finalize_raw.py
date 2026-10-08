"""One-off: convert raw model JSON (_proposal_raw / _ecs_raw) into output JSON."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CONFIDENCE_THRESHOLD, DEFAULT_OUTPUT_DIR  # noqa: E402
from pipeline import parse_model_json, validate  # noqa: E402

FILE_META = {
    "_proposal_raw.json": "Proposal Ashok.pdf",
    "_ecs_raw.json": "ECS.jpeg",
}


def convert(raw_name: str) -> dict:
    raw = (DEFAULT_OUTPUT_DIR / raw_name).read_text(encoding="utf-8")
    parsed = parse_model_json(raw)
    issues = validate(parsed)
    fields_out: list[dict] = []
    flagged: list[dict] = []
    for f in parsed.get("fields", []):
        conf = f.get("confidence", 0.0)
        e = {
            "name": f.get("name"),
            "value": f.get("value"),
            "confidence": round(float(conf), 2),
            "evidence": f.get("evidence", ""),
            "flagged": conf < CONFIDENCE_THRESHOLD,
        }
        if e["flagged"]:
            flagged.append({"field": e["name"], "confidence": e["confidence"]})
        fields_out.append(e)
    out = {
        "file": FILE_META[raw_name],
        "doc_type": parsed.get("doc_type"),
        "is_handwritten": parsed.get("is_handwritten"),
        "fields": fields_out,
        "flagged_fields": flagged,
        "schema_issues": issues,
    }
    dest = DEFAULT_OUTPUT_DIR / f"{Path(FILE_META[raw_name]).stem}.json"
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {dest.name}: {out['doc_type']} ({len(fields_out)} fields)")
    return out


if __name__ == "__main__":
    for name in sys.argv[1:] or list(FILE_META):
        try:
            convert(name)
        except FileNotFoundError:
            print(f"skip {name}: not found")
