from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import bass_swap_incoming_staged, bass_swap_outgoing_staged
from engine.transitions.lanes import (
  JunctionRender,
  align_junction,
  empty_junction_render,
  render_staged_blend,
)
from engine.transitions.overlap_utils import blend_sec_for_overlap

BASS_SWAP_BLEND_MIN_SEC = 1.2
BASS_SWAP_BLEND_FRACTION = 0.54


def render_bass_swap_junction(
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

  bass_out = bass_swap_outgoing_staged(tail)
  bass_in = bass_swap_incoming_staged(head)
  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=BASS_SWAP_BLEND_MIN_SEC,
    overlap_fraction=BASS_SWAP_BLEND_FRACTION,
  )
  return render_staged_blend(
    bass_out,
    bass_in,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.65,
    outgoing_fade_power=0.92,
  )


def bass_swap_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_bass_swap_junction(outgoing, incoming).as_overlap_chunk()
