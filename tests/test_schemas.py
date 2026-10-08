"""Offline tests for the Q3 pipeline (no API calls, LLMClient is mocked)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import parse_model_json, process_document, validate  # noqa: E402
from schemas import DOC_SCHEMAS, fields_for  # noqa: E402


class FakeClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls_made = 0

    def generate(self, contents, system):  # noqa: ANN001, ANN202
        import json

        return json.dumps(self.payload)


def _payload(doc_type: str, values: dict[str, str], conf: float = 0.9) -> dict:
    return {
        "doc_type": doc_type,
        "is_handwritten": "handwritten" in doc_type.lower(),
        "fields": [
            {"name": n, "value": v, "confidence": conf, "evidence": "x"}
            for n, v in values.items()
        ],
    }


def test_schemas_match_question_table() -> None:
    assert len(DOC_SCHEMAS) == 10
    assert fields_for("Passport") == [
        "Passport Number", "Date of Birth", "Date of Expiry", "MRZ Line 2",
    ]
    assert fields_for("Unknown Type") is None


def test_validate_clean_payload() -> None:
    p = _payload("PAN Card", {"PAN Number": "ABCDE1234F", "Full Name": "A",
                              "Father's Name": "B", "Date of Birth": "01/01/1990"})
    assert validate(p) == []


def test_validate_missing_and_extra_fields() -> None:
    p = _payload("PAN Card", {"PAN Number": "X"})
    issues = validate(p)
    assert any("missing fields" in i for i in issues)
    assert not any("unexpected" in i for i in issues)

    p2 = _payload("PAN Card", {"PAN Number": "X", "Full Name": "A",
                               "Father's Name": "B", "Date of Birth": "D", "Junk": "y"})
    assert any("unexpected fields" in i for i in validate(p2))


def test_validate_bad_confidence() -> None:
    p = _payload("PAN Card", {"PAN Number": "X", "Full Name": "A",
                              "Father's Name": "B", "Date of Birth": "D"})
    p["fields"][0]["confidence"] = 1.7
    assert any("bad confidence" in i for i in validate(p))


def test_parse_model_json_plain_and_fenced() -> None:
    obj = {"a": 1}
    assert parse_model_json('{"a": 1}') == obj
    assert parse_model_json('```json\n{"a": 1}\n```') == obj
    assert parse_model_json('Here you go:\n{"a": 1}\nthanks') == obj


def test_process_document_flags_low_confidence(tmp_path: Path) -> None:
    payload = _payload("NACH / ECS Mandate (handwritten)", {
        "Bank Account Number": "31004258912",
        "IFSC Code": "SBIN0277112",
        "Bank Name": "State Bank of India",
        "Amount (figures)": "50000",
        "Frequency": "Monthly",
    })
    payload["fields"][1]["confidence"] = 0.42  # IFSC barely legible
    client = FakeClient(payload)
    fake_file = tmp_path / "ECS.jpeg"
    fake_file.write_bytes(b"fake")  # render is monkeypatched out below

    import pipeline

    orig = pipeline.render_document
    pipeline.render_document = lambda p: [b"png"]
    try:
        result = process_document(fake_file, client)  # type: ignore[arg-type]
    finally:
        pipeline.render_document = orig

    assert result["doc_type"] == "NACH / ECS Mandate (handwritten)"
    assert result["is_handwritten"] is True
    assert len(result["fields"]) == 5
    assert result["flagged_fields"] == [
        {"field": "IFSC Code", "confidence": 0.42}
    ]
    assert result["fields"][1]["flagged"] is True
    assert result["fields"][0]["flagged"] is False
    assert result["schema_issues"] == []


def test_every_schema_type_is_handwritten_consistent() -> None:
    for dtype in DOC_SCHEMAS:
        assert ("handwritten" in dtype.lower()) == (dtype in {
            "NACH / ECS Mandate (handwritten)",
            "FATCA Annexure Form (handwritten)",
            "Benefit Illustration Declaration (handwritten)",
            "Moral Hazard Questionnaire (handwritten)",
            "Multiple Policies Consent Form (handwritten)",
            "Suitability Profiler Declaration (handwritten)",
        })


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
