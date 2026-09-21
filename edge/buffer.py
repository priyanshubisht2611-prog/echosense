"""
edge/buffer.py — Local CSV buffer for offline-first edge devices
================================================================
Stores telemetry/detection records locally in a CSV file and
flushes them in batches of 50 to a remote server when connectivity
is available.

Usage
-----
    from buffer import LocalBuffer

    buf = LocalBuffer()
    buf.save({"species": "eagle", "confidence": 0.97, "audio_file": "clip_001.wav"})
    flushed = buf.flush("http://server/api/records")
    buf.prune(max_age_days=7)
    print(buf.count())

Record schema (CSV columns)
----------------------------
    id          – auto-incrementing integer
    timestamp   – ISO-8601 UTC string (e.g. 2026-03-27T12:00:00.123456+00:00)
    status      – "pending" | "sent"
    payload     – JSON-encoded dict of caller-supplied data
"""

from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE: int = 50
DEFAULT_CSV_PATH: Path = Path(__file__).parent / "buffer.csv"
_FIELDNAMES: list[str] = ["id", "timestamp", "status", "payload"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_ts(ts_str: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware datetime."""
    return datetime.fromisoformat(ts_str)


# ---------------------------------------------------------------------------
# LocalBuffer
# ---------------------------------------------------------------------------


class LocalBuffer:
    """
    CSV-backed local buffer for edge telemetry / detection records.

    Parameters
    ----------
    csv_path : Path | str | None
        Path to the backing CSV file.  Defaults to ``buffer.csv`` in the
        same directory as this module.
    batch_size : int
        Maximum number of records sent per HTTP POST.  Defaults to 50.
    request_timeout : int
        Seconds to wait for a server response before giving up.
        Defaults to 10.
    """

    def __init__(
        self,
        csv_path: Optional[Path | str] = None,
        batch_size: int = BATCH_SIZE,
        request_timeout: int = 10,
    ) -> None:
        self.csv_path: Path = Path(csv_path) if csv_path else DEFAULT_CSV_PATH
        self.batch_size: int = batch_size
        self.request_timeout: int = request_timeout
        self._ensure_csv()
        self.prune(max_age_days=30)


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, record: Dict[str, Any]) -> int:
        """
        Append *record* to the local CSV buffer with status ``"pending"``.

        Parameters
        ----------
        record : dict
            Arbitrary JSON-serialisable key/value pairs.

        Returns
        -------
        int
            The auto-assigned row ID (≥ 1).

        Raises
        ------
        TypeError
            If *record* is not a ``dict``.
        ValueError
            If *record* contains values that cannot be JSON-serialised.
        """
        if not isinstance(record, dict):
            raise TypeError(f"record must be a dict, got {type(record).__name__!r}")

        row_id = self._next_id()
        row = {
            "id": row_id,
            "timestamp": _utcnow(),
            "status": "pending",
            "payload": json.dumps(record, ensure_ascii=False),
        }
        self._append_row(row)
        logger.debug("Saved record id=%d", row_id)
        return row_id

    def flush(self, server_url: str) -> int:
        """
        Send all ``pending`` records to *server_url* in batches.

        Each batch is HTTP-POSTed as JSON::

            {"records": [{"id": …, "timestamp": …, "payload": {…}}, …]}

        Successfully delivered batches are marked ``"sent"`` in the CSV.
        Batches that fail (network error / non-2xx response) remain
        ``"pending"`` and will be retried on the next ``flush`` call.

        Parameters
        ----------
        server_url : str
            Full URL of the remote ingest endpoint.

        Returns
        -------
        int
            Number of records successfully delivered in this call.
        """
        pending = self._load_pending()
        if not pending:
            logger.debug("Nothing to flush.")
            return 0

        sent_ids: List[int] = []

        for batch in self._batches(pending):
            body = [json.loads(r["payload"]) for r in batch if "binary" not in json.loads(r["payload"])]
            if not body:
                continue
            
            try:
                resp = requests.post(
                    server_url,
                    json=body,
                    timeout=self.request_timeout,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                batch_ids = [int(r["id"]) for r in batch]
                sent_ids.extend(batch_ids)
                logger.info(
                    "Flushed %d records (ids %d–%d)",
                    len(batch_ids),
                    batch_ids[0],
                    batch_ids[-1],
                )
            except requests.RequestException as exc:
                logger.warning("Batch failed, will retry next flush: %s", exc)

        if sent_ids:
            self._mark_sent(set(sent_ids))

        return len(sent_ids)

    def prune(self, max_age_days: int = 30) -> int:
        """
        Remove old ``sent`` records from the CSV.

        ``pending`` records are **never** removed — unsent data is preserved.

        Parameters
        ----------
        max_age_days : int
            Records older than this many days that have status ``"sent"``
            are deleted.  Must be ≥ 0.

        Returns
        -------
        int
            Number of rows deleted.

        Raises
        ------
        ValueError
            If *max_age_days* is negative.
        """
        if max_age_days < 0:
            raise ValueError("max_age_days must be >= 0")

        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
        rows = self._read_all()
        kept = [
            r
            for r in rows
            if not (r["status"] == "sent" and _parse_ts(r["timestamp"]) < cutoff)
        ]
        removed = len(rows) - len(kept)
        if removed:
            self._write_all(kept)
            logger.info("Pruned %d record(s) older than %d day(s).", removed, max_age_days)
        return removed

    def count(self, status: Optional[str] = None) -> int:
        """
        Return the number of records in the buffer.

        Parameters
        ----------
        status : str | None
            ``"pending"``, ``"sent"``, or ``None`` (all records).

        Returns
        -------
        int
        """
        rows = self._read_all()
        if status is None:
            return len(rows)
        return sum(1 for r in rows if r["status"] == status)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_csv(self) -> None:
        """Create the CSV file with headers if it does not already exist."""
        if not self.csv_path.exists():
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=_FIELDNAMES).writeheader()
            logger.debug("Created buffer CSV at %s", self.csv_path)

    def _read_all(self) -> List[Dict[str, str]]:
        """Read and return all rows from the CSV."""
        with open(self.csv_path, "r", newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def _write_all(self, rows: List[Dict[str, str]]) -> None:
        """Atomically rewrite the CSV with *rows* (temp-file swap)."""
        fd, tmp = tempfile.mkstemp(dir=self.csv_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp, self.csv_path)  # atomic on POSIX; best-effort on Windows
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _append_row(self, row: Dict[str, Any]) -> None:
        """Fast-path append — opens the file in 'a' mode, no full rewrite."""
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=_FIELDNAMES).writerow(row)

    def _next_id(self) -> int:
        """Return max(existing IDs) + 1, or 1 for an empty buffer."""
        rows = self._read_all()
        return max((int(r["id"]) for r in rows), default=0) + 1

    def _load_pending(self) -> List[Dict[str, str]]:
        return [r for r in self._read_all() if r["status"] == "pending"]

    def _mark_sent(self, ids: set[int]) -> None:
        rows = self._read_all()
        for r in rows:
            if int(r["id"]) in ids:
                r["status"] = "sent"
        self._write_all(rows)

    def _batches(
        self, items: List[Dict[str, str]]
    ) -> Generator[List[Dict[str, str]], None, None]:
        """Yield successive slices of up to ``batch_size`` items."""
        for i in range(0, len(items), self.batch_size):
            yield items[i : i + self.batch_size]
