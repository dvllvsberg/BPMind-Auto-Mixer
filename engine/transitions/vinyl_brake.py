from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import VINYL_BRAKE_SR, vinyl_rewind_brake_outgoing
from engine.transitions.lanes import (
  JunctionRender,
  align_junction,
  empty_junction_render,
  render_staged_blend,
)

VINYL_INCOMING_BLEND_SEC = 0.5


def render_vinyl_brake_junction(
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

  scratched = vinyl_rewind_brake_outgoing(tail)
  return render_staged_blend(
    scratched,
    head,
    incoming_blend_sec=VINYL_INCOMING_BLEND_SEC,
    incoming_fade_power=0.72,
    outgoing_fade_power=1.05,
    pin_tail_to_incoming=False,
  )


def vinyl_brake_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_vinyl_brake_junction(outgoing, incoming).as_overlap_chunk()
