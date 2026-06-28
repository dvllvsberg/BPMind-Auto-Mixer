from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import bass_swap_incoming_staged, bass_swap_outgoing_staged
from engine.transitions.overlap_utils import align_overlap, blend_sec_for_overlap, staged_tail_blend

BASS_SWAP_BLEND_MIN_SEC = 1.2
BASS_SWAP_BLEND_FRACTION = 0.54


def bass_swap_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  tail, head, overlap = align_overlap(outgoing, incoming)
  if overlap == 0:
    return np.zeros((0, tail.shape[1]), dtype=np.float32)

  bass_out = bass_swap_outgoing_staged(tail)
  bass_in = bass_swap_incoming_staged(head)
  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=BASS_SWAP_BLEND_MIN_SEC,
    overlap_fraction=BASS_SWAP_BLEND_FRACTION,
  )
  return staged_tail_blend(
    bass_out,
    bass_in,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.65,
    outgoing_fade_power=0.92,
  )
