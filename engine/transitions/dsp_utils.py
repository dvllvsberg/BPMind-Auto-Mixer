from __future__ import annotations

import numpy as np


def _ensure_2d(audio: np.ndarray) -> np.ndarray:
  if audio.ndim == 1:
    return audio.reshape(-1, 1)
  return audio


def one_pole_lowpass(audio: np.ndarray, alpha: float) -> np.ndarray:
  audio = _ensure_2d(audio)
  out = np.empty_like(audio)
  channels = audio.shape[1]
  for channel in range(channels):
    state = 0.0
    for index in range(len(audio)):
      sample = float(audio[index, channel])
      state = alpha * sample + (1.0 - alpha) * state
      out[index, channel] = state
  return out.astype(np.float32, copy=False)


def one_pole_highpass(audio: np.ndarray, alpha: float) -> np.ndarray:
  audio = _ensure_2d(audio)
  low = one_pole_lowpass(audio, alpha)
  return (audio - low).astype(np.float32, copy=False)


def progressive_lowpass(audio: np.ndarray, *, end_alpha: float = 0.06) -> np.ndarray:
  audio = _ensure_2d(audio)
  length = len(audio)
  out = np.empty_like(audio)
  channels = audio.shape[1]
  start_alpha = 0.75
  for channel in range(channels):
    state = 0.0
    for index in range(length):
      progress = index / max(length - 1, 1)
      alpha = start_alpha + (end_alpha - start_alpha) * progress
      sample = float(audio[index, channel])
      state = alpha * sample + (1.0 - alpha) * state
      out[index, channel] = state
  return out.astype(np.float32, copy=False)


def split_bass_treble(audio: np.ndarray, *, bass_alpha: float = 0.06) -> tuple[np.ndarray, np.ndarray]:
  bass = one_pole_lowpass(audio, bass_alpha)
  treble = audio - bass
  return bass.astype(np.float32, copy=False), treble.astype(np.float32, copy=False)


def bass_swap_outgoing(audio: np.ndarray) -> np.ndarray:
  """Снимаем бас с уходящего; к концу overlap только верх остаётся в миксе."""
  audio = _ensure_2d(audio)
  bass, treble = split_bass_treble(audio)
  bass_fade = np.linspace(1.0, 0.0, len(audio), dtype=np.float32) ** 1.1
  return (treble + bass * bass_fade.reshape(-1, 1)).astype(np.float32, copy=False)


def bass_swap_incoming(audio: np.ndarray) -> np.ndarray:
  """Бас входящего нарастает к концу overlap — последний сэмпл = исходный (стык с main body)."""
  audio = _ensure_2d(audio)
  bass, treble = split_bass_treble(audio)
  bass_rise = np.linspace(0.0, 1.0, len(audio), dtype=np.float32) ** 1.2
  return (treble + bass * bass_rise.reshape(-1, 1)).astype(np.float32, copy=False)


def progressive_wet_effect(
  audio: np.ndarray,
  wet_fn,
  *,
  start_wet: float,
  end_wet: float,
) -> np.ndarray:
  """Смешивание dry/wet по прогрессу; end_wet=0 → конец совпадает с исходником."""
  audio = _ensure_2d(audio)
  wet_signal = wet_fn(audio)
  length = len(audio)
  wet_amount = np.linspace(start_wet, end_wet, length, dtype=np.float32).reshape(-1, 1)
  dry_amount = 1.0 - wet_amount
  return (audio * dry_amount + wet_signal * wet_amount).astype(np.float32, copy=False)


def apply_echo_tail(
  audio: np.ndarray,
  *,
  delay_fraction: float = 0.22,
  feedback: float = 0.48,
) -> np.ndarray:
  """Классическое эхо на хвосте (reverse_swell и прочие утилиты)."""
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 4:
    return audio.astype(np.float32, copy=False)

  delay = max(int(length * delay_fraction), 1)
  wet = np.array(audio, dtype=np.float32, copy=True)
  for index in range(delay, length):
    wet[index] += audio[index - delay] * feedback
    if index >= delay * 2:
      wet[index] += audio[index - delay * 2] * (feedback * 0.55)

  dry_mix = 0.62
  return (audio * dry_mix + wet * (1.0 - dry_mix)).astype(np.float32, copy=False)


def _hallway_tap_delays(length: int) -> list[tuple[int, float]]:
  fractions = (0.06, 0.11, 0.18, 0.27, 0.38, 0.52)
  gains = (0.4, 0.35, 0.29, 0.23, 0.17, 0.12)
  return [(max(int(length * fraction), 1), gain) for fraction, gain in zip(fractions, gains)]


def _accumulate_hallway_taps(
  audio: np.ndarray,
  *,
  tap_scale: float = 1.0,
  darkness: float = 0.45,
) -> np.ndarray:
  audio = _ensure_2d(audio)
  length = len(audio)
  wet = np.zeros_like(audio)
  for delay, gain in _hallway_tap_delays(length):
    if delay >= length:
      continue
    delayed = np.zeros_like(audio)
    delayed[delay:] = audio[:-delay]
    muffled = one_pole_lowpass(delayed, max(0.12, darkness - (delay / max(length, 1)) * 0.25))
    wet += muffled * (gain * tap_scale)
  return wet.astype(np.float32, copy=False)


def hallway_decay_outgoing(audio: np.ndarray) -> np.ndarray:
  """Хвост уходит в «коридор»: отражения гаснут, dry постепенно затухает."""
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 8:
    return audio.astype(np.float32, copy=False)

  wet = _accumulate_hallway_taps(audio, tap_scale=1.05, darkness=0.5)
  progress = np.linspace(0.0, 1.0, length, dtype=np.float32).reshape(-1, 1)
  dry_env = np.power(1.0 - progress, 0.75)
  sine = np.sin(progress * np.pi)
  wet_env = np.where(sine > 1e-6, np.power(sine, 0.82), 0.0) * 1.05
  return (audio * dry_env + wet * wet_env).astype(np.float32, copy=False)


def hallway_swell_incoming(audio: np.ndarray) -> np.ndarray:
  """Обратный «коридор» на голове входящего; к концу overlap — исходный сигнал."""
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 16:
    return audio.astype(np.float32, copy=False)

  head_len = max(int(length * 0.3), 12)
  head = audio[:head_len]
  reversed_head = head[::-1].copy()
  swell = _accumulate_hallway_taps(reversed_head, tap_scale=0.85, darkness=0.42)
  swell_sine = np.sin(np.linspace(0.0, np.pi, head_len, dtype=np.float32).reshape(-1, 1))
  swell_env = np.where(swell_sine > 1e-6, np.power(swell_sine, 0.9), 0.0)
  swell = swell * swell_env

  overlay = np.zeros_like(audio)
  overlay[:head_len] = swell[::-1]

  overlay_fade = np.power(np.linspace(1.0, 0.0, length, dtype=np.float32), 1.1).reshape(-1, 1)
  overlay *= overlay_fade

  # Лёгкая коррекция громкости в начале → 1.0 к концу (стык с main body)
  gain = np.linspace(0.9, 1.0, length, dtype=np.float32).reshape(-1, 1)
  return (audio * gain + overlay * 0.62).astype(np.float32, copy=False)


VINYL_BRAKE_SR = 44100
# Короткий откат в конце — фиксированное время, не доля overlap.
VINYL_NUDGE_SEC = 0.09


def _vinyl_nudge_samples(length: int, *, sr: int = VINYL_BRAKE_SR) -> int:
  target = int(VINYL_NUDGE_SEC * sr)
  if length < target + 32:
    return max(0, min(length // 6, length - 16))
  return target


def _vinyl_platter_source_indices(
  progress: np.ndarray,
  length: int,
  *,
  sr: int = VINYL_BRAKE_SR,
) -> np.ndarray:
  """Монотонное торможение; микро-откат только в последние ~90 ms."""
  max_pos = float(length - 1)
  indices = (1.0 - np.power(1.0 - progress, 2.6)) * max_pos

  nudge = _vinyl_nudge_samples(length, sr=sr)
  if nudge < 16:
    return np.clip(indices, 0.0, max_pos)

  start = length - nudge
  local = np.linspace(0.0, 1.0, nudge, dtype=np.float32)
  peak = float(indices[start])
  dip = max(0.0, peak - max_pos * 0.05)
  pull = np.sin(local * (np.pi * 0.5))
  indices[start : start + nudge] = peak - pull * (peak - dip)
  settle = start + max(nudge // 3, 4)
  if settle < length:
    indices[settle:] = dip

  return np.clip(indices, 0.0, max_pos)


def vinyl_rewind_brake_outgoing(audio: np.ndarray, *, sr: int = VINYL_BRAKE_SR) -> np.ndarray:
  """DJ brake: одно замедление на всей длине overlap; откат — только ~90 ms в конце."""
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 16:
    return audio.astype(np.float32, copy=False)

  progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
  source_indices = _vinyl_platter_source_indices(progress, length, sr=sr)
  source_grid = np.arange(length, dtype=np.float32)

  out = np.empty_like(audio)
  for channel in range(audio.shape[1]):
    channel_data = audio[:, channel].astype(np.float32, copy=False)
    out[:, channel] = np.interp(source_indices, source_grid, channel_data)

  muffled = progressive_lowpass(out, end_alpha=0.07)
  darken = np.power(progress, 1.2).reshape(-1, 1) * 0.38
  out = out * (1.0 - darken) + muffled * darken

  nudge = _vinyl_nudge_samples(length, sr=sr)
  if nudge >= 16:
    nudge_zone = np.zeros(length, dtype=bool)
    nudge_zone[length - nudge :] = True
    out = np.where(nudge_zone.reshape(-1, 1), np.tanh(out * 1.1), out)

  volume = np.ones((length, 1), dtype=np.float32)
  fade_samples = min(int(0.35 * sr), length)
  fade_start = max(0, length - fade_samples)
  fade_progress = np.linspace(0.0, 1.0, length - fade_start, dtype=np.float32)
  volume[fade_start:, 0] = 1.0 - np.power(fade_progress, 1.1) * 0.9

  return (out * volume).astype(np.float32, copy=False)


def apply_gain_ramp(audio: np.ndarray, start: float, end: float) -> np.ndarray:
  audio = _ensure_2d(audio)
  if len(audio) == 0:
    return audio
  ramp = np.linspace(start, end, len(audio), dtype=np.float32).reshape(-1, 1)
  return (audio * ramp).astype(np.float32, copy=False)
