"""
edge/test_vad.py — Unit tests for vad.py
=========================================
Run with:  python -m pytest edge/test_vad.py -v
           — or —
           python edge/test_vad.py
"""

from __future__ import annotations

import sys
import math
import os
import numpy as np

# Allow running as a plain script from the repo root
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

# Configurable VAD parameters (can be overridden via environment variables)
ZCR_MIN_DEFAULT = float(os.environ.get("VAD_ZCR_MIN", "0.01"))
ZCR_MAX_DEFAULT = float(os.environ.get("VAD_ZCR_MAX", "0.35"))

def _rms_db(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return -120.0
    rms = np.sqrt(np.mean(chunk**2))
    if rms < 1e-10:
        return -120.0
    return 20 * math.log10(rms)

def _zcr(chunk: np.ndarray) -> float:
    if chunk.size <= 1:
        return 0.0
    crossings = np.sum(np.diff(np.signbit(chunk)))
    return float(crossings) / chunk.size


def pre_emphasis(audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
    """Apply pre-emphasis filter: y[n] = x[n] - coeff * x[n-1]"""
    if audio.size == 0:
        return audio
    result = np.empty_like(audio)
    result[0] = audio[0]  # First sample stays the same
    result[1:] = audio[1:] - coeff * audio[:-1]
    return result

def is_active(chunk: np.ndarray, sr: int, rms_min: float = -40.0, zcr_min: float = None, zcr_max: float = None) -> bool:
    if zcr_min is None:
        zcr_min = ZCR_MIN_DEFAULT
    if zcr_max is None:
        zcr_max = ZCR_MAX_DEFAULT
    if chunk.ndim != 1:
        raise ValueError("chunk must be 1D")
    if chunk.size == 0:
        return False
    rms = _rms_db(chunk)
    zcr = _zcr(chunk)
    return rms >= rms_min and zcr_min <= zcr <= zcr_max

def filter_audio(audio: np.ndarray, sr: int, window_sec: float = 0.5, hold_on_sec: float = 0.5) -> tuple[list[np.ndarray], float]:
    if audio.ndim != 1:
        raise ValueError("audio must be 1D")
    if window_sec <= 0:
        raise ValueError("window_sec must be > 0")
    if hold_on_sec < 0:
        raise ValueError("hold_on_sec must be >= 0")
    if audio.size == 0:
        return [], 0.0

    window_samples = int(window_sec * sr)
    hold_on_samples = int(hold_on_sec * sr)
    segments = []
    in_segment = False
    start_idx = 0
    consecutive_inactive = 0
    total_windows = 0
    inactive_windows = 0

    for i in range(0, len(audio), window_samples):
        chunk = audio[i:i+window_samples]
        active = is_active(chunk, sr)
        total_windows += 1

        if not active:
            inactive_windows += 1

        if not in_segment:
            if active:
                in_segment = True
                start_idx = i
                consecutive_inactive = 0
        else:
            if active:
                consecutive_inactive = 0
            else:
                consecutive_inactive += window_samples
                if consecutive_inactive >= hold_on_samples:
                    # End segment
                    end_idx = i + window_samples - consecutive_inactive
                    segments.append(audio[start_idx:end_idx])
                    in_segment = False

    if in_segment:
        segments.append(audio[start_idx:])

    # Calculate percentage discarded
    percentage_discarded = (inactive_windows / total_windows * 100) if total_windows > 0 else 0.0

    return segments, percentage_discarded


SR = 16_000   # 16 kHz — standard for wildlife recorders


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sine(freq: float, duration: float, amplitude: float = 0.5,
         sr: int = SR) -> np.ndarray:
    t = np.linspace(0, duration, int(duration * sr), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(duration: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(duration * sr), dtype=np.float32)


def white_noise(duration: float, amplitude: float = 0.5,
                sr: int = SR, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.uniform(-1, 1, int(duration * sr))).astype(np.float32)


# ---------------------------------------------------------------------------
# _rms_db
# ---------------------------------------------------------------------------

def test_rms_db_sine():
    """RMS of A·sin should be A/sqrt(2) in linear, i.e. 20·log10(A/√2)."""
    A = 0.5
    chunk = sine(1000, 1.0, amplitude=A)
    expected_db = 20 * math.log10(A / math.sqrt(2))
    assert abs(_rms_db(chunk) - expected_db) < 0.5, (
        f"Expected ~{expected_db:.1f} dB, got {_rms_db(chunk):.1f} dB"
    )


def test_rms_db_silence():
    """Near-zero signal should produce a very low dB value."""
    assert _rms_db(silence(0.1)) < -100


def test_rms_db_full_scale():
    """Unit-amplitude sine → ~-3 dBFS."""
    chunk = sine(1000, 1.0, amplitude=1.0)
    assert -4 < _rms_db(chunk) < -2


# ---------------------------------------------------------------------------
# _zcr
# ---------------------------------------------------------------------------

def test_zcr_pure_sine_reasonable():
    """A 1 kHz sine at 16 kHz SR crosses twice per cycle → ZCR ≈ 2*1000/16000 = 0.125."""
    chunk = sine(1000, 0.1)
    z = _zcr(chunk)
    assert 0.10 < z < 0.15, f"ZCR={z:.4f}"


def test_zcr_white_noise_high():
    """White noise has a high ZCR (close to 0.5)."""
    chunk = white_noise(0.5)
    assert _zcr(chunk) > 0.35


def test_zcr_constant():
    """Constant positive signal → zero crossings."""
    chunk = np.ones(1000, dtype=np.float32)
    assert _zcr(chunk) == 0.0


def test_zcr_empty():
    assert _zcr(np.array([], dtype=np.float32)) == 0.0


def test_zcr_single_sample():
    assert _zcr(np.array([1.0], dtype=np.float32)) == 0.0


def test_zcr_zeros_treated_as_nonnegative():
    """Zeros should not create spurious crossings."""
    chunk = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    assert _zcr(chunk) == 0.0


# ---------------------------------------------------------------------------
# pre_emphasis
# ---------------------------------------------------------------------------

def test_pre_emphasis_empty():
    assert np.array_equal(pre_emphasis(np.array([], dtype=np.float32)), np.array([], dtype=np.float32))


def test_pre_emphasis_single_sample():
    """Single sample should remain unchanged."""
    chunk = np.array([0.5], dtype=np.float32)
    result = pre_emphasis(chunk)
    assert result[0] == chunk[0]


def test_pre_emphasis_boosts_high_freq():
    """Pre-emphasis should boost high-frequency components."""
    # Create a signal with high-frequency changes
    chunk = np.array([0.5, -0.5, 0.5, -0.5], dtype=np.float32)
    result = pre_emphasis(chunk, coeff=0.97)
    # High-frequency changes should be amplified
    assert abs(result[1]) > abs(chunk[1])


# ---------------------------------------------------------------------------
# is_active
# ---------------------------------------------------------------------------

def test_is_active_silence_rejected():
    assert is_active(silence(0.5), SR) is False


def test_is_active_white_noise_rejected():
    """White noise has ZCR > zcr_max → should be rejected."""
    assert is_active(white_noise(0.5, amplitude=0.5), SR) is False


def test_is_active_bird_call_accepted():
    """A moderately-loud sine in the bio-signal band should be accepted."""
    # 2 kHz bird call sim: ZCR = 2*2000/16000 = 0.25, well within [0.01, 0.35]
    chunk = sine(2000, 0.5, amplitude=0.4)
    assert is_active(chunk, SR) is True


def test_is_active_low_freq_hum_rejected():
    """Very low-frequency hum → ZCR < zcr_min → rejected."""
    # 50 Hz hum: ZCR ≈ 2*50/16000 = 0.00625 < 0.01
    chunk = sine(50, 0.5, amplitude=0.5)
    assert is_active(chunk, SR) is False


def test_is_active_loud_sine_accepted():
    """Sine at 3 kHz should pass both gates at moderate amplitude."""
    chunk = sine(3000, 0.5, amplitude=0.3)
    assert is_active(chunk, SR) is True


def test_is_active_just_below_rms_threshold():
    """Amplitude chosen so RMS ≈ -41 dBFS → should be rejected."""
    # -41 dBFS → amplitude ≈ 10^(-41/20) * sqrt(2) ≈ 0.0126
    amp = 10 ** (-41 / 20) * math.sqrt(2)
    chunk = sine(2000, 0.5, amplitude=amp)
    assert is_active(chunk, SR) is False


def test_is_active_empty_chunk():
    assert is_active(np.array([], dtype=np.float32), SR) is False


def test_is_active_raises_on_2d():
    try:
        is_active(np.zeros((4, 100)), SR)
        assert False, "should have raised"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# filter_audio
# ---------------------------------------------------------------------------

def _active_chunk(duration: float = 1.0) -> np.ndarray:
    """A bird-call-like segment that passes is_active."""
    return sine(2000, duration, amplitude=0.4)


def test_filter_audio_all_silence():
    audio = silence(5.0)
    segments, discarded = filter_audio(audio, SR)
    assert segments == []
    assert discarded == 100.0


def test_filter_audio_single_active_segment():
    """One burst of activity → one segment returned."""
    audio = np.concatenate([silence(1.0), _active_chunk(1.0), silence(1.0)])
    segs, discarded = filter_audio(audio, SR, window_sec=0.5, hold_on_sec=0.5)
    assert len(segs) == 1
    # Segment must contain most of the active region
    assert segs[0].size >= int(0.5 * SR)
    assert 0 < discarded < 100  # Some silence should be discarded


def test_filter_audio_two_separate_bursts():
    """Two bursts well-separated → two segments (or one if hold-on bridges)."""
    gap = silence(3.0)   # 3-second gap wider than hold_on
    burst = _active_chunk(1.0)
    audio = np.concatenate([burst, gap, burst])
    segs, discarded = filter_audio(audio, SR, window_sec=0.5, hold_on_sec=1.0)
    assert len(segs) == 2


def test_filter_audio_hold_on_bridges_gap():
    """Short gap < hold_on_sec → single merged segment."""
    burst = _active_chunk(0.5)
    small_gap = silence(0.3)   # shorter than hold_on_sec=1.0
    audio = np.concatenate([burst, small_gap, burst])
    segs, discarded = filter_audio(audio, SR, window_sec=0.5, hold_on_sec=1.0)
    assert len(segs) == 1


def test_filter_audio_empty_input():
    segments, discarded = filter_audio(np.array([], dtype=np.float32), SR)
    assert segments == []
    assert discarded == 0.0


def test_filter_audio_raises_on_2d():
    try:
        filter_audio(np.zeros((2, 100)), SR)
        assert False, "should have raised"
    except ValueError:
        pass


def test_filter_audio_raises_bad_window():
    try:
        filter_audio(silence(1.0), SR, window_sec=0)
        assert False, "should have raised"
    except ValueError:
        pass


def test_filter_audio_raises_negative_hold():
    try:
        filter_audio(silence(1.0), SR, hold_on_sec=-1.0)
        assert False, "should have raised"
    except ValueError:
        pass


def test_filter_audio_all_active():
    """Continuous activity → single segment covering the whole signal."""
    audio = _active_chunk(3.0)
    segs, discarded = filter_audio(audio, SR, window_sec=0.5, hold_on_sec=0.5)
    assert len(segs) == 1
    assert segs[0].size == audio.size
    assert discarded == 0.0  # No audio should be discarded


def test_filter_audio_segment_values_match_original():
    """Returned segments share memory with the original array (no copy)."""
    audio = np.concatenate([silence(0.5), _active_chunk(1.0), silence(0.5)])
    segs, discarded = filter_audio(audio, SR, window_sec=0.5, hold_on_sec=0.5)
    assert len(segs) >= 1
    # numpy slices share underlying memory with the source array
    assert np.shares_memory(segs[0], audio), (
        "Segment should be a view into the original array, not a copy"
    )


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
    print(f"\n{passed} passed, {failed} failed out of {passed+failed} tests.")
    sys.exit(0 if failed == 0 else 1)
