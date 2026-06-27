from __future__ import annotations

import numpy as np

from engine.transitions.crossfade import crossfade_segments
from engine.transitions.dsp_utils import hallway_decay_outgoing, hallway_swell_incoming


def echo_out_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  hallway_out = hallway_decay_outgoing(outgoing)
  hallway_in = hallway_swell_incoming(incoming)
  return crossfade_segments(hallway_out, hallway_in, incoming_delay=0.48)
