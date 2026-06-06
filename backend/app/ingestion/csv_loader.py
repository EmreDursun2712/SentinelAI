"""Stream CSV rows from a binary file-like object.

Yields one ``RowResult`` per data row so the calling service can choose how to
batch, count, and surface errors. Memory use is O(1) in the row count.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

from app.ingestion.parser import ParsedFlow, parse_row


class CsvFormatError(Exception):
    """The CSV file itself is unreadable (missing header, bad encoding, etc.)."""


@dataclass(frozen=True)
class RowResult:
    row_number: int
    parsed: ParsedFlow | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.parsed is not None


def stream_csv(file: BinaryIO) -> Iterator[RowResult]:
    """Yield one ``RowResult`` per data row. Header errors raise ``CsvFormatError``."""
    text = io.TextIOWrapper(file, encoding="utf-8", errors="replace", newline="")
    reader = csv.DictReader(text)
    if not reader.fieldnames:
        raise CsvFormatError("CSV is empty or missing a header row.")

    for index, raw in enumerate(reader, start=1):
        try:
            parsed = parse_row(raw)
        except Exception as exc:  # pydantic.ValidationError, ValueError, anything
            yield RowResult(row_number=index, parsed=None, error=_short_error(exc))
            continue
        yield RowResult(row_number=index, parsed=parsed, error=None)


def _short_error(exc: BaseException) -> str:
    msg = str(exc).strip().replace("\n", " | ")
    return msg[:240] if msg else exc.__class__.__name__
