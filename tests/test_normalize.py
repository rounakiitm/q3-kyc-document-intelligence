from normalize import normalize_aadhaar, normalize_date, normalize_field, normalize_pan


def test_normalize_identity_fields():
    assert normalize_pan("abcde1234f") == "ABCDE1234F"
    assert normalize_aadhaar("1234-5678-9012") == "1234 5678 9012"
    assert normalize_date("2024/01/15") == "15-01-2024"
    assert normalize_field("Full Name", "RAHUL  KUMAR") == "Rahul Kumar"
    assert normalize_field("IFSC Code", "hdfc0001234") == "HDFC0001234"


def test_nullish_values():
    assert normalize_field("Date", None) is None
    assert normalize_field("Date", "n/a") is None
