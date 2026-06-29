from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import one_pole_highpass, progressive_lowpass
from engine.transitions.lanes import (
  JunctionRender,
  align_junction,
  empty_junction_render,
  render_staged_blend,
)
from engine.transitions.overlap_utils import blend_sec_for_overlap

FILTER_BLEND_MIN_SEC = 1.15
FILTER_BLEND_FRACTION = 0.52


def filter_sweep_lowpass_tail(audio: np.ndarray) -> np.ndarray:
  """LP-sweep: к концу overlap звук явно «под водой»."""
  if audio.size == 0:
    return audio

  if audio.ndim == 1:
    audio = audio.reshape(-1, 1)

  length = len(audio)
  filtered = progressive_lowpass(audio, end_alpha=0.012)
  progress = np.linspace(0.0, 1.0, length, dtype=np.float32).reshape(-1, 1)
  wet = np.power(progress, 0.62)
  dry = 1.0 - wet * 0.88
  muffled = filtered * (0.45 + 0.55 * wet)
  return (audio * dry + muffled * wet).astype(np.float32, copy=False)


def filter_sweep_highpass_head(audio: np.ndarray) -> np.ndarray:
  """HP на голове входящего; к концу overlap — исходный сигнал."""
  if audio.size == 0:
    return audio

  if audio.ndim == 1:
    audio = audio.reshape(-1, 1)

  length = len(audio)
  bright = one_pole_highpass(audio, alpha=0.78)
  progress = np.linspace(0.0, 1.0, length, dtype=np.float32).reshape(-1, 1)
  wet = np.power(1.0 - progress, 0.92)
  return (audio * (1.0 - wet * 0.95) + bright * (wet * 0.95)).astype(np.float32, copy=False)


def render_filter_sweep_junction(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  if outgoing.size == 0:
    return JunctionRender(incoming.astype(np.float32, copy=False))
  if incoming.size == 0:
    return JunctionRender(outgoing.astype(np.float32, copy=False))

  tail, head, overlap = align_junction(outgoing, incoming)
  if overlap == 0:
    return empty_junction_render(tail.shape[1] if tail.size else 2)

  swept = filter_sweep_lowpass_tail(tail)
  filtered_in = filter_sweep_highpass_head(head)
  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=FILTER_BLEND_MIN_SEC,
    overlap_fraction=FILTER_BLEND_FRACTION,
  )
  return render_staged_blend(
    swept,
    filtered_in,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.62,
    outgoing_fade_power=0.88,
  )


def filter_sweep_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_filter_sweep_junction(outgoing, incoming).as_overlap_chunk()
