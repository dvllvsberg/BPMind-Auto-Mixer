from __future__ import annotations

import numpy as np

from engine.transitions.crossfade import crossfade_segments
from engine.transitions.dsp_utils import apply_gain_ramp


def impact_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  dipped_out = apply_gain_ramp(outgoing, 1.0, 0.42)
  punch_in = apply_gain_ramp(incoming, 1.32, 1.0)
  return crossfade_segments(dipped_out, punch_in, incoming_delay=0.75, outgoing_release=1.35)
