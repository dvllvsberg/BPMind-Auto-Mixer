from __future__ import annotations

import numpy as np

from engine.transitions.crossfade import crossfade_segments
from engine.transitions.dsp_utils import bass_swap_incoming, bass_swap_outgoing


def bass_swap_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  bass_out = bass_swap_outgoing(outgoing)
  bass_in = bass_swap_incoming(incoming)
  return crossfade_segments(bass_out, bass_in)
