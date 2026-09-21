"""
edge/test_buffer.py — Unit tests for buffer.py
================================================
Run with:  python -m pytest edge/test_buffer.py -v
           — or —
           python edge/test_buffer.py
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow running as a plain script from the repo root
sys.path.insert(0, str(Path(__file__).parent))
from buffer import LocalBuffer, _FIELDNAMES, BATCH_SIZE


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_buf(**kwargs) -> tuple[LocalBuffer, Path]:
    """Return a LocalBuffer backed by a fresh temp CSV."""
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp.close()
    Path(tmp.name).unlink()          # Let LocalBuffer create it fresh
    buf = LocalBuffer(csv_path=tmp.name, **kwargs)
    return buf, Path(tmp.name)


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _fake_response(status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(
        side_effect=None if 200 <= status_code < 300
        else __import__("requests").HTTPError(f"HTTP {status_code}")
    )
    return resp


# ---------------------------------------------------------------------------
# CSV initialisation
# ---------------------------------------------------------------------------


def test_csv_created_on_init():
    buf, path = make_buf()
    assert path.exists(), "CSV file should be created on __init__"
    rows = _read_csv(path)
    assert rows == [], "Newly created CSV should have no data rows"


def test_csv_has_correct_headers():
    buf, path = make_buf()
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        headers = next(reader)
    assert headers == _FIELDNAMES


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------


def test_save_returns_id():
    buf, _ = make_buf()
    rid = buf.save({"species": "eagle", "conf": 0.9})
    assert rid == 1


def test_save_increments_id():
    buf, _ = make_buf()
    id1 = buf.save({"a": 1})
    id2 = buf.save({"b": 2})
    assert id2 == id1 + 1


def test_save_writes_pending_status():
    buf, path = make_buf()
    buf.save({"x": 1})
    row = _read_csv(path)[0]
    assert row["status"] == "pending"


def test_save_encodes_payload_as_json():
    buf, path = make_buf()
    data = {"species": "owl", "confidence": 0.88, "meta": {"site": "A"}}
    buf.save(data)
    row = _read_csv(path)[0]
    assert json.loads(row["payload"]) == data


def test_save_requires_dict():
    buf, _ = make_buf()
    try:
        buf.save(["not", "a", "dict"])
        assert False, "should have raised TypeError"
    except TypeError:
        pass


def test_save_timestamp_is_utc_iso():
    buf, path = make_buf()
    before = datetime.now(tz=timezone.utc)
    buf.save({"k": "v"})
    after = datetime.now(tz=timezone.utc)
    row = _read_csv(path)[0]
    ts = datetime.fromisoformat(row["timestamp"])
    assert ts.tzinfo is not None, "timestamp must be timezone-aware"
    assert before <= ts <= after


def test_save_multiple_records():
    buf, path = make_buf()
    for i in range(5):
        buf.save({"i": i})
    assert len(_read_csv(path)) == 5


# ---------------------------------------------------------------------------
# count()
# ---------------------------------------------------------------------------


def test_count_empty():
    buf, _ = make_buf()
    assert buf.count() == 0


def test_count_total():
    buf, _ = make_buf()
    buf.save({"a": 1})
    buf.save({"b": 2})
    assert buf.count() == 2


def test_count_by_status():
    buf, _ = make_buf()
    buf.save({"a": 1})
    buf.save({"b": 2})
    assert buf.count("pending") == 2
    assert buf.count("sent") == 0


# ---------------------------------------------------------------------------
# flush()
# ---------------------------------------------------------------------------


def test_flush_empty_buffer_returns_zero():
    buf, _ = make_buf()
    sent = buf.flush("http://example.com/api")
    assert sent == 0


def test_flush_marks_records_as_sent():
    buf, path = make_buf()
    for i in range(3):
        buf.save({"i": i})

    with patch("requests.post", return_value=_fake_response(200)):
        sent = buf.flush("http://example.com/api")

    assert sent == 3
    rows = _read_csv(path)
    assert all(r["status"] == "sent" for r in rows)


def test_flush_sends_correct_payload():
    buf, _ = make_buf()
    buf.save({"species": "hawk", "conf": 0.75})

    captured = []

    def fake_post(url, json=None, **kwargs):
        captured.append(json)
        return _fake_response(200)

    with patch("requests.post", side_effect=fake_post):
        buf.flush("http://example.com/api")

    assert len(captured) == 1
    records = captured[0]["records"]
    assert len(records) == 1
    assert records[0]["payload"] == {"species": "hawk", "conf": 0.75}


def test_flush_batches_large_buffer():
    buf, _ = make_buf(batch_size=10)
    for i in range(25):
        buf.save({"i": i})

    call_count = []

    def fake_post(url, json=None, **kwargs):
        call_count.append(len(json["records"]))
        return _fake_response(200)

    with patch("requests.post", side_effect=fake_post):
        sent = buf.flush("http://example.com/api")

    assert sent == 25
    assert call_count == [10, 10, 5]      # 3 batches


def test_flush_leaves_pending_on_network_error():
    buf, path = make_buf()
    for i in range(3):
        buf.save({"i": i})

    import requests as req_mod
    with patch("requests.post", side_effect=req_mod.ConnectionError("timeout")):
        sent = buf.flush("http://unreachable.invalid/api")

    assert sent == 0
    rows = _read_csv(path)
    assert all(r["status"] == "pending" for r in rows)


def test_flush_partial_success_across_batches():
    """First batch fails, second succeeds → only second batch marked sent."""
    buf, path = make_buf(batch_size=2)
    for i in range(4):
        buf.save({"i": i})

    import requests as req_mod
    call_num = [0]

    def alternating(url, json=None, **kwargs):
        call_num[0] += 1
        if call_num[0] == 1:
            raise req_mod.ConnectionError("fail first batch")
        return _fake_response(200)

    with patch("requests.post", side_effect=alternating):
        sent = buf.flush("http://example.com/api")

    assert sent == 2    # second batch only
    rows = _read_csv(path)
    statuses = [r["status"] for r in rows]
    assert statuses.count("sent") == 2
    assert statuses.count("pending") == 2


def test_flush_does_not_resend_already_sent():
    buf, _ = make_buf()
    buf.save({"a": 1})

    with patch("requests.post", return_value=_fake_response(200)):
        buf.flush("http://example.com/api")   # first flush

    call_count = []
    with patch("requests.post", side_effect=lambda *a, **kw: call_count.append(1) or _fake_response(200)):
        buf.flush("http://example.com/api")   # second flush

    assert call_count == [], "Already-sent records must not be re-submitted"


def test_flush_uses_default_batch_size():
    buf, _ = make_buf()
    assert buf.batch_size == BATCH_SIZE


# ---------------------------------------------------------------------------
# prune()
# ---------------------------------------------------------------------------


def test_prune_returns_count():
    buf, _ = make_buf()
    assert buf.prune() == 0   # nothing to prune yet


def test_prune_removes_old_sent_records():
    buf, path = make_buf()
    buf.save({"a": 1})   # pending  → must NOT be pruned
    buf.save({"b": 2})   # will be made 'sent' and old

    # Manually mark row 2 as sent with an old timestamp
    rows = buf._read_all()
    old_ts = (datetime.now(tz=timezone.utc) - timedelta(days=40)).isoformat()
    rows[1]["status"] = "sent"
    rows[1]["timestamp"] = old_ts
    buf._write_all(rows)

    removed = buf.prune(max_age_days=30)
    assert removed == 1
    remaining = _read_csv(path)
    assert len(remaining) == 1
    assert remaining[0]["status"] == "pending"


def test_prune_keeps_recent_sent():
    buf, path = make_buf()
    buf.save({"a": 1})
    rows = buf._read_all()
    rows[0]["status"] = "sent"    # sent, but just now → within max_age
    buf._write_all(rows)

    removed = buf.prune(max_age_days=30)
    assert removed == 0
    assert len(_read_csv(path)) == 1


def test_prune_never_removes_pending():
    buf, path = make_buf()
    buf.save({"a": 1})
    # Put an old timestamp but keep it pending
    rows = buf._read_all()
    rows[0]["timestamp"] = (datetime.now(tz=timezone.utc) - timedelta(days=100)).isoformat()
    buf._write_all(rows)

    removed = buf.prune(max_age_days=30)
    assert removed == 0


def test_prune_rejects_negative_days():
    buf, _ = make_buf()
    try:
        buf.prune(max_age_days=-1)
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_prune_zero_days_removes_all_sent():
    buf, path = make_buf()
    buf.save({"x": 1})
    buf.save({"y": 2})
    rows = buf._read_all()
    for r in rows:
        r["status"] = "sent"
        r["timestamp"] = (datetime.now(tz=timezone.utc) - timedelta(seconds=1)).isoformat()
    buf._write_all(rows)

    removed = buf.prune(max_age_days=0)
    assert removed == 2
    assert _read_csv(path) == []


# ---------------------------------------------------------------------------
# Atomicity / edge cases
# ---------------------------------------------------------------------------


def test_csv_persists_across_instances():
    """A new LocalBuffer pointed at the same file sees previous records."""
    buf1, path = make_buf()
    buf1.save({"persisted": True})

    buf2 = LocalBuffer(csv_path=path)
    assert buf2.count() == 1


def test_large_payload_round_trips():
    buf, path = make_buf()
    big = {f"key_{i}": f"value_{i}" * 10 for i in range(100)}
    buf.save(big)
    row = _read_csv(path)[0]
    assert json.loads(row["payload"]) == big


def test_unicode_payload():
    buf, path = make_buf()
    data = {"bird": "鸟", "note": "café ñoño 🐦"}
    buf.save(data)
    row = _read_csv(path)[0]
    assert json.loads(row["payload"]) == data


# ---------------------------------------------------------------------------
# Runner (plain script mode)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {passed + failed} tests.")
    sys.exit(0 if failed == 0 else 1)
