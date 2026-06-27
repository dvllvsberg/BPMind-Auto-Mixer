"""Tape Stop — мотор глохнет на уходящем; на входящем мотор раскручивается снова (без crossfade)."""

from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import _ensure_2d, one_pole_lowpass, progressive_lowpass

TAPE_STOP_SR = 44100
_MIN_MOTOR_RATE = 0.02
_STOP_RATE_FLOOR = 0.14
_START_RATE_FLOOR = 0.46

# Подъём на входящем резче спуска (меньше степень → круче «горка вверх»).
_START_RATE_POWER = 0.52

# Тихие интро: подтянуть уровень до разгона, чтобы эффект был слышен (не подрезка — makeup).
_SPIN_TARGET_RMS = 0.13
_SPIN_MAX_MAKEUP_GAIN = 3.0


def _fix_length(signal: np.ndarray, length: int) -> np.ndarray:
  import librosa

  signal = signal.astype(np.float32, copy=False)
  if len(signal) == length:
    return signal
  return librosa.util.fix_length(signal, size=length)


def _motor_rate_stop(progress: np.ndarray) -> np.ndarray:
  """Плавный спуск; в ноль только в последних ~12%, без длинного «мёртвого» хвоста."""
  base = np.maximum(np.cos(progress * (np.pi * 0.5)), _STOP_RATE_FLOOR)
  tail = np.clip((progress - 0.88) / 0.12, 0.0, 1.0)
  return (base * (1.0 - tail)).astype(np.float32)


def _motor_rate_start(progress: np.ndarray) -> np.ndarray:
  """Зеркальный, но более резкий подъём — с пола скорости, без старта из нуля."""
  rising = np.sin(progress * (np.pi * 0.5))
  curved = np.power(np.maximum(rising, 0.0), _START_RATE_POWER)
  rate = _START_RATE_FLOOR + (1.0 - _START_RATE_FLOOR) * curved
  return rate.astype(np.float32)


def apply_quiet_spin_makeup(audio: np.ndarray) -> np.ndarray:
  """Поднять тихую голову входящего перед tape spin — иначе эффект теряется на fade-in трека."""
  audio = _ensure_2d(audio)
  if audio.size == 0:
    return audio
  rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64)))))
  if rms < 1e-7 or rms >= _SPIN_TARGET_RMS:
    return audio.astype(np.float32, copy=False)
  gain = min(_SPIN_MAX_MAKEUP_GAIN, _SPIN_TARGET_RMS / rms)
  return (audio * gain).astype(np.float32, copy=False)


def _read_variable_rate(channel: np.ndarray, rates: np.ndarray, length: int) -> np.ndarray:
  """Resample-чтение с непрерывно меняющейся скоростью мотора."""
  channel = channel.astype(np.float32, copy=False)
  if length < 2:
    return _fix_length(channel, length)

  rates = np.maximum(rates.astype(np.float64), _MIN_MOTOR_RATE)
  travel = min((length - 1) * float(np.mean(rates)), len(channel) - 1.0)
  travel = max(travel, 1.0)

  increments = rates / np.sum(rates) * travel
  source_indices = np.concatenate([[0.0], np.cumsum(increments[:-1])])

  mean_rate = float(np.mean(rates))
  anti_alias = max(0.06, mean_rate * 0.7)
  filtered = one_pole_lowpass(channel.reshape(-1, 1), anti_alias)[:, 0]
  source_grid = np.arange(len(channel), dtype=np.float64)
  return np.interp(source_indices, source_grid, filtered).astype(np.float32, copy=False)


def _tape_motor_ramp(
  audio: np.ndarray,
  *,
  descending: bool,
  tone_darkens: bool,
  volume_dies: bool,
) -> np.ndarray:
  audio = _ensure_2d(audio)
  length = len(audio)
  if length < 64:
    return audio.astype(np.float32, copy=False)

  progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
  if descending:
    rates = _motor_rate_stop(progress)
  else:
    rates = _motor_rate_start(progress)

  channels = audio.shape[1]
  out = np.empty((length, channels), dtype=np.float32)
  for channel in range(channels):
    out[:, channel] = _read_variable_rate(audio[:, channel], rates, length)

  if tone_darkens:
    tone_mix = np.power(progress, 1.6).reshape(-1, 1) * 0.22
  else:
    tone_mix = np.power(1.0 - progress, 1.6).reshape(-1, 1) * 0.22
  muffled = progressive_lowpass(out, end_alpha=0.06)
  out = out * (1.0 - tone_mix) + muffled * tone_mix

  motor_edge = 0.90 if volume_dies else 0.0
  volume = np.ones((length, 1), dtype=np.float32)
  if volume_dies:
    dying = progress >= motor_edge
    if np.any(dying):
      fade_progress = np.clip(
        (progress[dying] - motor_edge) / (1.0 - motor_edge),
        0.0,
        1.0,
      )
      volume[dying, 0] = np.power(
        np.sin((1.0 - fade_progress) * (np.pi * 0.5)),
        1.35,
      ).astype(np.float32)

  out = (out * volume).astype(np.float32, copy=False)
  return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def tape_motor_stop_outgoing(audio: np.ndarray, *, sr: int = TAPE_STOP_SR) -> np.ndarray:
  _ = sr
  return _tape_motor_ramp(audio, descending=True, tone_darkens=True, volume_dies=True)


def tape_motor_start_incoming(audio: np.ndarray, *, sr: int = TAPE_STOP_SR) -> np.ndarray:
  """«Отпустили кассету» — мотор разгоняется, тон и скорость возвращаются к норме."""
  _ = sr
  boosted = apply_quiet_spin_makeup(audio)
  return _tape_motor_ramp(boosted, descending=False, tone_darkens=False, volume_dies=False)


def tape_stop_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return tape_motor_stop_outgoing(outgoing)

  return tape_motor_stop_outgoing(outgoing)
