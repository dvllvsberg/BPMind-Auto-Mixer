from __future__ import annotations

import numpy as np

OPENING_TRACK_FADE_IN_SEC = 4.0
OPENING_TRACK_FADE_OUT_SEC = 3.5
OPENING_FADE_CURVE_POWER = 1.18
MAX_FADE_TRACK_FRACTION = 0.62
OUTPUT_SR = 44100


def _ensure_2d(audio: np.ndarray) -> np.ndarray:
  if audio.ndim == 1:
    return audio.reshape(-1, 1)
  return audio


def cosine_fade_in_envelope(
  length: int,
  *,
  fade_frames: int,
  curve_power: float = OPENING_FADE_CURVE_POWER,
) -> np.ndarray:
  if length <= 0 or fade_frames <= 0:
    return np.ones(max(length, 0), dtype=np.float32)
  fade_frames = min(fade_frames, length)
  env = np.ones(length, dtype=np.float32)
  phase = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
  ramp = 0.5 * (1.0 - np.cos(phase * np.pi))
  env[:fade_frames] = np.power(ramp, curve_power)
  return env


def cosine_fade_out_envelope(
  length: int,
  *,
  fade_frames: int,
  curve_power: float = OPENING_FADE_CURVE_POWER,
) -> np.ndarray:
  if length <= 0 or fade_frames <= 0:
    return np.ones(max(length, 0), dtype=np.float32)
  fade_frames = min(fade_frames, length)
  env = np.ones(length, dtype=np.float32)
  phase = np.linspace(0.0, 1.0, fade_frames, dtype=np.float32)
  ramp = 0.5 * (1.0 + np.cos(phase * np.pi))
  env[-fade_frames:] = np.power(ramp, curve_power)
  return env


def apply_opening_track_main_envelope(
  audio: np.ndarray,
  *,
  fade_in_sec: float = OPENING_TRACK_FADE_IN_SEC,
  fade_out_sec: float = OPENING_TRACK_FADE_OUT_SEC,
  apply_fade_out: bool = True,
  sr: int = OUTPUT_SR,
) -> np.ndarray:
  """Fade-in в начале микса; fade-out только если после main нет overlap-перехода."""
  audio = _ensure_2d(audio)
  length = len(audio)
  if length == 0:
    return audio

  max_fade_frames = max(int(length * MAX_FADE_TRACK_FRACTION), 1)
  fade_in_frames = min(int(round(fade_in_sec * sr)), max_fade_frames)
  env = cosine_fade_in_envelope(length, fade_frames=fade_in_frames)

  if apply_fade_out:
    fade_out_frames = min(int(round(fade_out_sec * sr)), max_fade_frames)
    env *= cosine_fade_out_envelope(length, fade_frames=fade_out_frames)

  return (audio * env.reshape(-1, 1)).astype(np.float32, copy=False)


def apply_dip_zone_fade_out(
  audio: np.ndarray,
  *,
  dip_start_frame: int,
) -> np.ndarray:
  """Плавный fade-out на участке pitch-dip (конец первого трека в impact)."""
  audio = _ensure_2d(audio).astype(np.float32, copy=True)
  length = len(audio)
  dip_start = min(max(dip_start_frame, 0), length)
  dip_len = length - dip_start
  if dip_len <= 1:
    return audio

  phase = np.linspace(0.0, 1.0, dip_len, dtype=np.float32)
  ramp = 0.5 * (1.0 + np.cos(phase * np.pi))
  env = np.power(ramp, 1.22)
  audio[dip_start:] *= env.reshape(-1, 1)
  return audio
