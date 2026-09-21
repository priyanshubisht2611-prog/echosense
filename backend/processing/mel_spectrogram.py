"""
backend/processing/mel_spectrogram.py - Mel Spectrogram Extraction
=================================================================
Extracts mel spectrograms from audio with configurable parameters.
"""

import numpy as np
import librosa
from typing import Optional, Tuple


def pre_emphasis(audio: np.ndarray, coeff: float = 0.97) -> np.ndarray:
    """
    Apply pre-emphasis filter: y[n] = x[n] - coeff * x[n-1]
    
    Args:
        audio: Input audio array
        coeff: Pre-emphasis coefficient (default 0.97)
    
    Returns:
        Pre-emphasized audio array
    """
    if audio.size == 0:
        return audio
    result = np.empty_like(audio)
    result[0] = audio[0]
    result[1:] = audio[1:] - coeff * audio[:-1]
    return result


def extract_mel_spectrogram(
    audio: np.ndarray,
    sr: int,
    n_mels: int = 64,
    frame_length: int = 25,  # ms
    hop_length: int = 10,  # ms
    apply_pre_emphasis: bool = True,
    apply_hamming: bool = True,
    apply_log: bool = True,
    normalize: bool = False,
    training_mean: Optional[float] = None,
    training_std: Optional[float] = None,
) -> np.ndarray:
    """
    Extract mel spectrogram from audio.
    
    Args:
        audio: Input audio array
        sr: Sample rate
        n_mels: Number of mel bins (default 64)
        frame_length: Frame length in milliseconds (default 25)
        hop_length: Hop length in milliseconds (default 10)
        apply_pre_emphasis: Apply pre-emphasis filter (default True)
        apply_hamming: Apply Hamming window (default True)
        apply_log: Apply log compression (default True)
        normalize: Apply normalization (default False)
        training_mean: Mean for normalization (if normalize=True)
        training_std: Std for normalization (if normalize=True)
    
    Returns:
        Mel spectrogram (n_mels, n_frames)
    """
    # Convert frame/hop lengths to samples
    n_fft = int(frame_length * sr / 1000)
    hop_length_samples = int(hop_length * sr / 1000)
    
    # Pre-emphasis
    if apply_pre_emphasis:
        audio = pre_emphasis(audio)
    
    # Extract mel spectrogram using librosa
    mel_spec = librosa.feature.melspectrogram(
        y=audio,
        sr=sr,
        n_fft=n_fft,
        hop_length=hop_length_samples,
        n_mels=n_mels,
        window='hamming' if apply_hamming else 'hann',
        center=True,
        pad_mode='reflect'
    )
    
    # Log compression
    if apply_log:
        mel_spec = np.log(mel_spec + 1e-6)
    
    # Normalization
    if normalize:
        if training_mean is not None and training_std is not None:
            mel_spec = (mel_spec - training_mean) / training_std
        else:
            # Normalize per spectrogram (mean=0, std=1)
            mel_spec = (mel_spec - np.mean(mel_spec)) / (np.std(mel_spec) + 1e-8)
    
    return mel_spec
