"""Source validation — safe file validation before parsing.

Validates MIME, extension, size, encoding, and structural integrity.
Blocks macros in XLSX, oversized files, malformed structure.
Validation is deterministic and conservative.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

ALLOWED_MIME = {
    "text/csv": "csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB

MAGIC_CSV = b","  # CSVs have no magic bytes — handled by extension/content sniff
MAGIC_XLSX = b"PK\x03\x04"  # XLSX is a ZIP archive


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    file_kind: str  # "csv" | "xlsx" | "unknown"
    mime_type: str
    encoding: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_upload(
    data: bytes,
    filename: str,
    declared_mime: str | None = None,
    max_size: int = MAX_FILE_SIZE,
) -> ValidationResult:
    """Validate a file upload for safety and structure.

    Returns ValidationResult with valid=True/False and diagnostic messages.
    Never raises — returns a result. The caller decides what to do.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Size check
    if len(data) > max_size:
        errors.append(f"File size {len(data)} exceeds maximum {max_size}")
        return ValidationResult(
            valid=False,
            file_kind="unknown",
            mime_type=declared_mime or "",
            encoding=None,
            errors=errors,
        )

    if len(data) == 0:
        errors.append("File is empty")
        return ValidationResult(
            valid=False,
            file_kind="unknown",
            mime_type=declared_mime or "",
            encoding=None,
            errors=errors,
        )

    # 2. Extension check
    lower_name = filename.lower()
    ext = ""
    if "." in lower_name:
        ext = "." + lower_name.rsplit(".", 1)[-1]

    if ext not in ALLOWED_EXTENSIONS:
        errors.append(f"Extension '{ext}' not allowed. Allowed: {ALLOWED_EXTENSIONS}")

    # 3. MIME / content-type sniff
    file_kind = "unknown"
    sniffed_mime = _sniff_mime(data)

    if sniffed_mime == "xlsx" or ext == ".xlsx":
        file_kind = "xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if not data.startswith(MAGIC_XLSX):
            errors.append("File declared as XLSX but magic bytes do not match a ZIP archive")
        else:
            macro_check = _check_xlsx_macros(data)
            if macro_check:
                errors.append(f"XLSX contains unsafe content: {macro_check}")
    elif sniffed_mime == "csv" or ext == ".csv":
        file_kind = "csv"
        mime_type = "text/csv"
    else:
        mime_type = declared_mime or sniffed_mime or "unknown"
        if declared_mime and declared_mime in ALLOWED_MIME:
            file_kind = ALLOWED_MIME[declared_mime]
        elif ext in ALLOWED_EXTENSIONS:
            file_kind = "xlsx" if ext == ".xlsx" else "csv"
            mime_type = (
                "text/csv"
                if file_kind == "csv"
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            errors.append(
                f"Unable to determine file type from content or extension. Sniffed: '{sniffed_mime}'"
            )

    # 4. Declared MIME check
    if declared_mime and declared_mime not in ALLOWED_MIME:
        errors.append(f"Declared MIME '{declared_mime}' not in allowed set: {ALLOWED_MIME}")

    encoding = None
    if file_kind == "csv" and not errors:
        encoding = _detect_encoding(data)
        if encoding is None:
            warnings.append("Could not determine encoding; files should be UTF-8")

    if errors:
        return ValidationResult(
            valid=False,
            file_kind=file_kind,
            mime_type=mime_type,
            encoding=encoding,
            errors=errors,
            warnings=warnings,
        )

    return ValidationResult(
        valid=True, file_kind=file_kind, mime_type=mime_type, encoding=encoding, warnings=warnings
    )


def _sniff_mime(data: bytes) -> str:
    """Sniff file type from leading bytes."""
    if data[:4] == MAGIC_XLSX:
        return "xlsx"
    if b"\n" in data[:4096] or b"," in data[:4096]:
        return "csv"
    return "unknown"


def _check_xlsx_macros(data: bytes) -> str | None:
    """Check XLSX for macro-enabled workbook markers. Returns message if unsafe."""
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        # Look for VBA macro project files
        vba_pattern = re.compile(r"vbaProject|\.vba|macros/", re.IGNORECASE)
        for name in names:
            if vba_pattern.search(name):
                return f"contains VBA macro component: {name}"
        # Check for activeX content
        for name in names:
            if "activeX" in name.lower():
                return f"contains ActiveX component: {name}"
        return None
    except zipfile.BadZipFile:
        return "malformed ZIP archive"
    except Exception:
        return "unable to read XLSX structure"


def _detect_encoding(data: bytes) -> str | None:
    """Detect encoding of CSV bytes."""
    if data[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        data.decode("latin-1")
        return "latin-1"
    except UnicodeDecodeError:
        pass
    return None
