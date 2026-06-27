"""Поиск «настоящего» входа в трек после тихого дубля / fade-in (секция 1 → секция 2)."""

from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

HOP_LENGTH = 512
DEFAULT_BASELINE_SEC = 1.2
DEFAULT_JUMP_DB = 7.0
DEFAULT_SUSTAIN_SEC = 0.35
DEFAULT_MIN_SKIP_SEC = 0.25


def detect_loud_entry_sec(
  y: np.ndarray,
  sr: int,
  *,
  from_sec: float = 0.0,
  baseline_sec: float = DEFAULT_BASELINE_SEC,
  jump_db: float = DEFAULT_JUMP_DB,
  sustain_sec: float = DEFAULT_SUSTAIN_SEC,
) -> float:
  """Первая устойчивая точка, где уровень заметно выше тихого префикса."""
  if y.size == 0 or sr <= 0:
    return from_sec

  if y.ndim > 1:
    y = np.mean(y, axis=1)

  rms = librosa.feature.rms(y=y, hop_length=HOP_LENGTH)[0]
  if rms.size == 0:
    return from_sec

  peak = float(np.max(rms))
  if peak <= 1e-9:
    return from_sec

  rms_db = librosa.amplitude_to_db(rms, ref=peak)
  frame_sec = HOP_LENGTH / sr

  kernel = max(3, int(round(0.12 / frame_sec)) | 1)
  kernel_vec = np.ones(kernel, dtype=np.float64) / kernel
  smoothed = np.convolve(rms_db, kernel_vec, mode="same")

  baseline_frames = max(1, int(round(baseline_sec / frame_sec)))
  baseline_frames = min(baseline_frames, len(smoothed))
  baseline = float(np.median(smoothed[:baseline_frames]))

  sustain_frames = max(1, int(round(sustain_sec / frame_sec)))
  threshold = baseline + jump_db

  for index in range(baseline_frames, len(smoothed) - sustain_frames + 1):
    window = smoothed[index : index + sustain_frames]
    if float(np.median(window)) >= threshold:
      return from_sec + index * frame_sec

  return from_sec


def _load_scan_segment(path: str | Path, from_sec: float, scan_sec: float) -> tuple[np.ndarray, int]:
  file_path = Path(path)
  with sf.SoundFile(file_path) as audio_file:
    sr = audio_file.samplerate
    start_frame = max(0, int(from_sec * sr))
    end_frame = min(int((from_sec + scan_sec) * sr), audio_file.frames)
    if end_frame <= start_frame:
      return np.zeros((0, 1), dtype=np.float32), sr
    audio_file.seek(start_frame)
    data = audio_file.read(end_frame - start_frame, dtype="float32", always_2d=True)
  return data, sr


def detect_loud_entry_from_path(
  path: str | Path,
  from_sec: float,
  *,
  scan_sec: float = 45.0,
) -> float:
  audio, sr = _load_scan_segment(path, from_sec, scan_sec)
  return detect_loud_entry_sec(audio, sr, from_sec=from_sec)


def intro_skip_sec(
  path: str | Path,
  play_from_sec: float,
  *,
  scan_sec: float = 45.0,
  min_skip_sec: float = DEFAULT_MIN_SKIP_SEC,
) -> float:
  file_path = Path(path)
  if not file_path.is_file():
    return 0.0
  try:
    entry = detect_loud_entry_from_path(file_path, play_from_sec, scan_sec=scan_sec)
  except (OSError, RuntimeError):
    return 0.0
  skip = max(0.0, entry - play_from_sec)
  if skip < min_skip_sec:
    return 0.0
  return skip
