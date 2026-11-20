"""Process-local admission control for memory-intensive XLSX parsing."""

from contextlib import contextmanager
from threading import BoundedSemaphore
from collections.abc import Iterator

from app.ingestion.contracts import SourceFileError

# v0.1 runs one API process. A process-local non-blocking gate prevents
# concurrent workbook object graphs from multiplying memory use. A future
# multi-worker deployment must move this gate to a dedicated worker service.
_XLSX_READER_SLOTS = BoundedSemaphore(value=1)


@contextmanager
def xlsx_reader_slot() -> Iterator[None]:
    """Acquire the single XLSX parser slot or fail quickly with a retryable error."""
    if not _XLSX_READER_SLOTS.acquire(blocking=False):
        raise SourceFileError(
            "XLSX_READER_BUSY",
            "An Excel workbook is already being processed. Retry shortly.",
        )
    try:
        yield
    finally:
        _XLSX_READER_SLOTS.release()
