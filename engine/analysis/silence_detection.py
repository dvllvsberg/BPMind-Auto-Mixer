from __future__ import annotations

import librosa
import numpy as np

HOP_LENGTH = 512
DEFAULT_SILENCE_THRESHOLD_DB = -38.0
DEFAULT_MIN_SILENCE_SEC = 2.0


def detect_content_bounds(
  y: np.ndarray,
  sr: int,
  *,
  silence_threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
  min_silence_sec: float = DEFAULT_MIN_SILENCE_SEC,
  hop_length: int = HOP_LENGTH,
) -> tuple[float, float]:
  """Найти границы музыкального содержимого без длинной тишины в начале/конце."""
  duration = float(len(y) / sr)
  if duration <= 0:
    return 0.0, 0.0

  rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
  peak = float(np.max(rms))
  if peak <= 0:
    return 0.0, duration

  rms_db = librosa.amplitude_to_db(rms, ref=peak)
  frame_sec = hop_length / sr
  min_frames = max(1, int(round(min_silence_sec / frame_sec)))

  content_start = 0.0
  silent_run = 0
  for index, db in enumerate(rms_db):
    if db <= silence_threshold_db:
      silent_run += 1
      continue
    if silent_run >= min_frames:
      content_start = index * frame_sec
    break

  content_end = duration
  silent_run = 0
  for index in range(len(rms_db) - 1, -1, -1):
    if rms_db[index] <= silence_threshold_db:
      silent_run += 1
      continue
    if silent_run >= min_frames:
      content_end = duration - silent_run * frame_sec
    else:
      content_end = min(duration, (index + 1) * frame_sec)
    break

  content_start = max(0.0, min(content_start, duration))
  content_end = max(content_start, min(content_end, duration))
  return round(content_start, 3), round(content_end, 3)
