from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio_segment(
  path: str | Path,
  start_sec: float = 0.0,
  end_sec: float | None = None,
) -> tuple[np.ndarray, int]:
  file_path = Path(path)
  if not file_path.is_file():
    raise FileNotFoundError(f"Файл не найден: {file_path}")

  with sf.SoundFile(file_path) as audio_file:
    sr = audio_file.samplerate
    start_frame = max(0, int(start_sec * sr))
    end_frame = audio_file.frames if end_sec is None else min(int(end_sec * sr), audio_file.frames)
    if end_frame <= start_frame:
      return np.zeros((0, 1), dtype=np.float32), sr

    audio_file.seek(start_frame)
    frames = end_frame - start_frame
    data = audio_file.read(frames, dtype="float32", always_2d=True)

  return data, sr
