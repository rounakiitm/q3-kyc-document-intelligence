"""Structural format verification for KYC fields (PAN, Aadhaar, IFSC, …)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Indian PAN: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# Aadhaar: 12 digits (not starting with 0/1)
AADHAAR_RE = re.compile(r"^[2-9][0-9]{11}$")
# IFSC: 4 letters + 0 + 6 alphanumeric
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
# Passport (Indian ordinary): 1 letter + 7 digits (common); also allow 8–9 alnum
PASSPORT_RE = re.compile(r"^[A-Z][0-9]{7}$|^[A-Z0-9]{8,9}$")
# DL: state code + year + serial — keep flexible but require letters+digits
DL_RE = re.compile(r"^[A-Z]{2}[0-9A-Z\-\s]{8,20}$")
# Policy / application numbers in this dataset are long digit strings
POLICY_RE = re.compile(r"^[0-9]{8,20}$")
# Bank account: 9–18 digits
ACCOUNT_RE = re.compile(r"^[0-9]{9,18}$")
# MRZ line 2 typically 44 chars (TD3) — allow 30–44 for partial reads
MRZ_RE = re.compile(r"^[A-Z0-9<]{30,44}$")


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def validate_date(text: str) -> tuple[bool, str]:
    raw = (text or "").strip()
    if not raw:
        return False, "empty date"
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year < 1900 or dt.year > 2100:
                return False, f"date year out of range: {dt.year}"
            return True, "ok"
        except ValueError:
            continue
    return False, "date must be DD-MM-YYYY (after normalization)"


def validate_field_format(name: str, value: Any) -> dict[str, Any]:
    """Return {ok, rule, message} for a named field value."""
    key = (name or "").casefold()
    if value is None or str(value).strip() == "":
        return {"ok": True, "rule": "empty", "message": "no value to validate"}

    text = str(value).strip()

    if "aadhaar" in key:
        digits = _digits(text)
        ok = bool(AADHAAR_RE.match(digits))
        return {
            "ok": ok,
            "rule": "aadhaar_12_digits",
            "message": "ok" if ok else "Aadhaar must be 12 digits (not starting with 0/1)",
        }

    if key in {"pan number", "tin / pan"} or (key.endswith("pan") and "company" not in key):
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        ok = bool(PAN_RE.match(compact))
        return {
            "ok": ok,
            "rule": "pan_AAAAA9999A",
            "message": "ok" if ok else "PAN must match AAAAA9999A (5 letters, 4 digits, 1 letter)",
        }

    if "ifsc" in key:
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        ok = bool(IFSC_RE.match(compact))
        return {
            "ok": ok,
            "rule": "ifsc_AAAA0XXXXXX",
            "message": "ok" if ok else "IFSC must match AAAA0XXXXXX (4 letters, 0, 6 alnum)",
        }

    if "account number" in key or "bank account" in key:
        digits = _digits(text)
        ok = bool(ACCOUNT_RE.match(digits))
        return {
            "ok": ok,
            "rule": "account_9_18_digits",
            "message": "ok" if ok else "Bank account must be 9–18 digits",
        }

    if "passport number" in key:
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        ok = bool(PASSPORT_RE.match(compact))
        return {
            "ok": ok,
            "rule": "passport_alnum",
            "message": "ok" if ok else "Passport number format looks invalid",
        }

    if key == "dl number" or "driving" in key and "number" in key:
        compact = re.sub(r"\s+", "", text.upper())
        ok = bool(DL_RE.match(compact))
        return {
            "ok": ok,
            "rule": "dl_state_serial",
            "message": "ok" if ok else "DL number should start with a 2-letter state code",
        }

    if "mrz" in key:
        compact = re.sub(r"\s+", "", text.upper())
        ok = bool(MRZ_RE.match(compact))
        return {
            "ok": ok,
            "rule": "mrz_line2",
            "message": "ok" if ok else "MRZ line 2 should be 30–44 chars (A–Z, 0–9, <)",
        }

    if any(t in key for t in ("policy number", "application number", "application/proposal")):
        digits = _digits(text)
        # Some application numbers may be alphanumeric — only enforce when mostly digits
        if digits and len(digits) >= 8 and len(digits) == len(re.sub(r"\s", "", text)):
            ok = bool(POLICY_RE.match(digits))
            return {
                "ok": ok,
                "rule": "policy_digits",
                "message": "ok" if ok else "Policy/application number should be 8–20 digits",
            }
        return {"ok": True, "rule": "policy_loose", "message": "ok"}

    if any(
        t in key
        for t in (
            "date of birth",
            "date of issue",
            "date of expiry",
            "valid till",
        )
    ) or key == "date":
        ok, msg = validate_date(text)
        return {"ok": ok, "rule": "date_dd_mm_yyyy", "message": msg}

    if "amount" in key:
        ok = bool(re.search(r"\d", text))
        return {
            "ok": ok,
            "rule": "amount_numeric",
            "message": "ok" if ok else "Amount must contain digits",
        }

    return {"ok": True, "rule": "none", "message": "no structural rule"}


def apply_format_validation(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each field with format_ok / format_rule / format_message; flag failures."""
    out = []
    for f in fields:
        entry = dict(f)
        check = validate_field_format(str(entry.get("name") or ""), entry.get("value"))
        entry["format_ok"] = check["ok"]
        entry["format_rule"] = check["rule"]
        entry["format_message"] = check["message"]
        if entry.get("value") not in (None, "") and not check["ok"]:
            entry["flagged"] = True
            entry["flag_reasons"] = list(
                dict.fromkeys((entry.get("flag_reasons") or []) + ["format_invalid"])
            )
        out.append(entry)
    return out
