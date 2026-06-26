from __future__ import annotations

import numpy as np

from engine.domain.enums import TransitionType
from engine.transitions.crossfade import crossfade_segments
from engine.transitions.filter_sweep import filter_sweep_mix


def mix_transition_segments(
  transition_type: TransitionType,
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> np.ndarray:
  kind = transition_type.normalized()

  if len(outgoing) == 0:
    return incoming.astype(np.float32, copy=False)
  if len(incoming) == 0:
    return outgoing.astype(np.float32, copy=False)

  if kind is TransitionType.CUT:
    return np.concatenate([outgoing, incoming], axis=0).astype(np.float32, copy=False)

  if kind is TransitionType.FILTER_SWEEP:
    return filter_sweep_mix(outgoing, incoming)

  return crossfade_segments(outgoing, incoming)
