from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import reverb_out_incoming, reverb_out_outgoing
from engine.transitions.overlap_utils import align_overlap, blend_sec_for_overlap, staged_tail_blend

REVERB_BLEND_MIN_SEC = 1.25
REVERB_BLEND_FRACTION = 0.5


def echo_out_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """Reverb-out: хвост уходящего в reverb, входящий dry подмешивается в конце."""
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  tail, head, overlap = align_overlap(outgoing, incoming)
  if overlap == 0:
    return np.zeros((0, tail.shape[1]), dtype=np.float32)

  reverbed = reverb_out_outgoing(tail)
  dry_in = reverb_out_incoming(head)
  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=REVERB_BLEND_MIN_SEC,
    overlap_fraction=REVERB_BLEND_FRACTION,
  )
  return staged_tail_blend(
    reverbed,
    dry_in,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.58,
    outgoing_fade_power=0.82,
  )
