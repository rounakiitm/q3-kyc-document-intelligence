"""Classification + extraction prompts for the Q3 pipeline."""
from __future__ import annotations

import json

from schemas import DOC_SCHEMAS

SYSTEM_PROMPT = """You are a meticulous document-understanding engine for an insurance \
onboarding pipeline. You receive one scanned document (possibly multi-page) and must:

1. CLASSIFY it as exactly one of the document types listed in the schema, and \
give a classification_confidence (0.0-1.0) for that type decision.
2. EXTRACT every required field for that type.
3. SELF-ASSESS a confidence score (0.0-1.0) for EACH field.

Rules:
- For handwritten values, read carefully character by character. Account numbers, \
IFSC codes, TIN/PAN, dates and place names must be transcribed exactly as written.
- A "value" must be a plain string (digits/letters only for codes - no spaces or \
labels). Dates in DD/MM/YYYY. If a field is genuinely absent or unreadable, set \
value to null and confidence to 0.0 - never guess.
- "evidence" is a short verbatim snippet of what you read on the page.
- Confidence rubric: 0.95+ printed, crisp text; 0.80-0.95 legible handwriting; \
0.50-0.80 messy/ambiguous handwriting where some interpretation was needed; \
below 0.50 only when barely legible.
- "is_handwritten" refers to the filled-in entries, not the printed form template.
- If the document clearly matches NONE of the types above (e.g. an assignment form, \
proposal form, or any other form type not listed), set doc_type to exactly \
"Other (no extraction schema)", extract the 5-8 most important filled-in fields as \
free-form name/value pairs, and keep honest per-field confidences.
- Respond with JSON only, exactly matching the requested structure."""

SCHEMA_BLOCK = json.dumps(
    {dtype: {"fields": fields} for dtype, fields in DOC_SCHEMAS.items()},
    indent=2,
)

USER_TEMPLATE = """Document types and their required fields:

{schema}

Classify this document and extract its fields. Respond with JSON of exactly this shape:

{{
  "doc_type": "<one of the types above>",
  "classification_confidence": <0.0-1.0>,
  "is_handwritten": <true|false>,
  "fields": [
    {{"name": "<field name>", "value": "<string|null>", "confidence": <0.0-1.0>, \
"evidence": "<verbatim snippet>"}}
  ]
}}

Include ONLY the fields required for the classified type."""
