from __future__ import annotations

import numpy as np

from engine.transitions.crossfade import crossfade_segments
from engine.transitions.dsp_utils import one_pole_highpass, progressive_wet_effect


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
      muffled = progress**1.35
      alpha = 0.9 - muffled * 0.88
      alpha = max(alpha, 0.012)
      sample = float(audio[index, channel])
      state = alpha * sample + (1.0 - alpha) * state
      volume = 1.0 - muffled * 0.55
      out[index, channel] = state * volume

  return out.astype(np.float32, copy=False)


def filter_sweep_incoming_head(audio: np.ndarray) -> np.ndarray:
  """Краткий HP на голове входящего; к концу overlap — исходный сигнал (без скачка)."""
  return progressive_wet_effect(
    audio,
    lambda signal: one_pole_highpass(signal, alpha=0.86),
    start_wet=0.55,
    end_wet=0.0,
  )


def filter_sweep_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  swept = filter_sweep_tail(outgoing)
  filtered_in = filter_sweep_incoming_head(incoming)
  return crossfade_segments(swept, filtered_in, incoming_delay=0.38, outgoing_release=1.2)
