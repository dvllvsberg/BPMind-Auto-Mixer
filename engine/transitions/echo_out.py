from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import reverb_out_incoming, reverb_out_outgoing
from engine.transitions.lanes import (
  JunctionRender,
  align_junction,
  empty_junction_render,
  render_staged_blend,
)
from engine.transitions.overlap_utils import blend_sec_for_overlap

REVERB_BLEND_MIN_SEC = 1.25
REVERB_BLEND_FRACTION = 0.5


def render_echo_out_junction(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  """Reverb-out: хвост уходящего в reverb, входящий dry подмешивается в конце."""
  if outgoing.size == 0:
    return JunctionRender(incoming.astype(np.float32, copy=False))
  if incoming.size == 0:
    return JunctionRender(outgoing.astype(np.float32, copy=False))

  tail, head, overlap = align_junction(outgoing, incoming)
  if overlap == 0:
    return empty_junction_render(tail.shape[1] if tail.size else 2)

  reverbed = reverb_out_outgoing(tail)
  dry_in = reverb_out_incoming(head)
  blend_sec = blend_sec_for_overlap(
    overlap,
    min_sec=REVERB_BLEND_MIN_SEC,
    overlap_fraction=REVERB_BLEND_FRACTION,
  )
  return render_staged_blend(
    reverbed,
    dry_in,
    incoming_blend_sec=blend_sec,
    incoming_fade_power=0.58,
    outgoing_fade_power=0.82,
  )


def echo_out_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_echo_out_junction(outgoing, incoming).as_overlap_chunk()
