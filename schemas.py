"""Extraction schemas for the 10 document types listed in the assessment.

The field names exactly mirror the "Required extraction targets by document
type" table in Questions.docx so outputs can be scored against the answer key.
"""
from __future__ import annotations

# Ordered mapping: document type -> required fields (order preserved for output).
DOC_SCHEMAS: dict[str, list[str]] = {
    "Aadhaar Card": [
        "Aadhaar Number",
        "Full Name",
        "Date of Birth",
        "Address",
    ],
    "PAN Card": [
        "PAN Number",
        "Full Name",
        "Father's Name",
        "Date of Birth",
    ],
    "Driving Licence": [
        "DL Number",
        "Name",
        "Date of Issue",
        "Valid Till date",
    ],
    "Passport": [
        "Passport Number",
        "Date of Birth",
        "Date of Expiry",
        "MRZ Line 2",
    ],
    "NACH / ECS Mandate (handwritten)": [
        "Bank Account Number",
        "IFSC Code",
        "Bank Name",
        "Amount (figures)",
        "Frequency",
    ],
    "FATCA Annexure Form (handwritten)": [
        "Policy Number",
        "TIN / PAN",
        "Father's Name",
        "Place of Birth",
        "Nationality",
    ],
    "Benefit Illustration Declaration (handwritten)": [
        "Application Number",
        "Policyholder Name",
        "Date",
        "Place",
    ],
    "Moral Hazard Questionnaire (handwritten)": [
        "Application Number",
        "Name of Life Assured",
        "Nominee Relationship",
        "Date",
        "Place",
    ],
    "Multiple Policies Consent Form (handwritten)": [
        "Proposer Name",
        "Reason for Multiple Policies (selected checkbox)",
        "Date",
        "Place",
    ],
    "Suitability Profiler Declaration (handwritten)": [
        "Application Number",
        "Name of Life Assured",
        "Name of Agent/SP",
        "Date",
        "Place",
    ],
}

# Types whose source documents are predominantly handwritten forms.
HANDWRITTEN_TYPES = {k for k in DOC_SCHEMAS if "handwritten" in k.lower()}


def fields_for(doc_type: str) -> list[str] | None:
    """Return the required fields for a type, or None if no schema exists."""
    return DOC_SCHEMAS.get(doc_type)
