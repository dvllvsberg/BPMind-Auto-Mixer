from __future__ import annotations

import numpy as np


def filter_sweep_tail(audio: np.ndarray) -> np.ndarray:
  """LP-sweep на хвосте: к концу сегмента звук заметно «уходит под воду»."""
  if audio.size == 0:
    return audio

  if audio.ndim == 1:
    audio = audio.reshape(-1, 1)

  length = len(audio)
  out = np.empty_like(audio)
  channels = audio.shape[1]

  for channel in range(channels):
    state = 0.0
    for index in range(length):
      progress = index / max(length - 1, 1)
      # Квадратичный спад: в начале overlap почти полный сигнал, к концу сильное LP
      muffled = progress**1.6
      alpha = 0.88 - muffled * 0.84
      alpha = max(alpha, 0.04)
      sample = float(audio[index, channel])
      state = alpha * sample + (1.0 - alpha) * state
      volume = 1.0 - muffled * 0.35
      out[index, channel] = state * volume

  return out.astype(np.float32, copy=False)


def filter_sweep_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """Фильтр на уходящем + обычный crossfade — входящий заходит поверх «приглушённого» хвоста."""
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  from engine.transitions.crossfade import crossfade_segments

  swept = filter_sweep_tail(outgoing)
  return crossfade_segments(swept, incoming)
