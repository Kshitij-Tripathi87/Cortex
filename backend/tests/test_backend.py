"""Backend tests — storage, validation, profiler, service, compiler."""

from app.modules.inference.rules_provider import normalize_column_name, suggest_mapping
from app.modules.sources.profiler import profile_csv
from app.modules.sources.storage import build_storage_key, compute_checksum
from app.modules.sources.validation import validate_upload


def test_checksum_deterministic():
    data = b"test,data\n1,2\n"
    cs1 = compute_checksum(data)
    cs2 = compute_checksum(data)
    assert cs1 == cs2


def test_checksum_different():
    cs1 = compute_checksum(b"data1")
    cs2 = compute_checksum(b"data2")
    assert cs1 != cs2


def test_storage_key_deterministic():
    ws = "00000000-0000-0000-0000-000000000001"
    checksum = "abc123"
    key1 = build_storage_key(ws, checksum)
    key2 = build_storage_key(ws, checksum)
    assert key1 == key2
    assert key1 == f"workspaces/{ws}/uploads/{checksum}"


def test_validation_valid_csv():
    data = b"col1,col2\nval1,val2\n"
    result = validate_upload(data, "test.csv")
    assert result.valid is True
    assert result.file_kind == "csv"


def test_validation_invalid_extension():
    data = b"some,data\n"
    result = validate_upload(data, "test.txt")
    assert result.valid is False
    assert "not allowed" in result.errors[0]


def test_validation_oversized():
    data = b"x" * (201 * 1024 * 1024 + 1)
    result = validate_upload(data, "test.csv")
    assert result.valid is False
    assert "exceeds maximum" in result.errors[0]


def test_profiler_csv_basic():
    data = b"name,age,active\nAlice,30,true\nBob,25,false\n"
    profile = profile_csv(data)
    assert profile.row_count == 2
    assert profile.column_count == 3
    assert len(profile.columns) == 3
    assert profile.columns[0].column_name == "name"


def test_normalize_column():
    assert normalize_column_name("Supplier Name") == "supplier_name"
    assert normalize_column_name("VENDOR-ID") == "vendor_id"
    assert normalize_column_name("  PO Number  ") == "po_number"


def test_suggest_mapping_known():
    result = suggest_mapping("supplier_name")
    assert result.canonical_entity == "Supplier"
    assert result.canonical_field == "legal_name"
    assert result.confidence == 1.0
    assert result.requires_review is False


def test_suggest_mapping_unknown():
    result = suggest_mapping("unknown_column_xyz")
    assert result.canonical_entity is None
    assert result.canonical_field is None
    assert result.confidence == 0.0
    assert result.requires_review is True
