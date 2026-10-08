from crosscheck import cross_document_common_fields
from validate_format import validate_field_format


def test_pan_format():
    assert validate_field_format("PAN Number", "ABCDE1234F")["ok"]
    assert not validate_field_format("PAN Number", "ABCD1234F")["ok"]
    assert not validate_field_format("PAN Number", "12345ABCDE")["ok"]


def test_aadhaar_ifsc_account():
    assert validate_field_format("Aadhaar Number", "2345 6789 0123")["ok"]
    assert not validate_field_format("Aadhaar Number", "1234 5678 9012")["ok"]  # starts with 1
    assert validate_field_format("IFSC Code", "HDFC0001234")["ok"]
    assert not validate_field_format("IFSC Code", "HDFC1001234")["ok"]
    assert validate_field_format("Bank Account Number", "123456789012")["ok"]


def test_cross_document_name_mismatch():
    results = [
        {
            "file": "aadhaar.png",
            "fields": [{"name": "Full Name", "value": "Ashok Kumar", "confidence": 0.95}],
        },
        {
            "file": "pan.png",
            "fields": [{"name": "Full Name", "value": "Ashok Kumar", "confidence": 0.95}],
        },
        {
            "file": "form.png",
            "fields": [{"name": "Proposer Name", "value": "Ashok Kumarr", "confidence": 0.9}],
        },
    ]
    out = cross_document_common_fields(results)
    name = next(g for g in out["common_fields"] if g["group"] == "applicant_name")
    assert name["status"] == "MISMATCH"
    assert out["flags"]
