from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import impact_punch_head
from engine.transitions.overlap_utils import OVERLAP_SR, align_overlap, blend_sec_for_overlap, staged_tail_blend

IMPACT_BLEND_MIN_SEC = 0.95
IMPACT_BLEND_FRACTION = 0.48


def impact_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  tail, head, overlap = align_overlap(outgoing, incoming)
  if overlap == 0:
    return np.zeros((0, tail.shape[1]), dtype=np.float32)

  progress = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
  out_env = np.power(1.0 - progress, 2.4).reshape(-1, 1)
  dipped = tail * out_env * 0.32
  punched = impact_punch_head(head)

  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=IMPACT_BLEND_MIN_SEC,
    overlap_fraction=IMPACT_BLEND_FRACTION,
  )
  return staged_tail_blend(
    dipped,
    punched,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.55,
    outgoing_fade_power=1.15,
  )
