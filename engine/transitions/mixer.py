from __future__ import annotations

import numpy as np

from engine.domain.enums import TransitionType
from engine.transitions.crossfade import crossfade_segments
from engine.transitions.bass_swap import bass_swap_mix
from engine.transitions.echo_out import echo_out_mix
from engine.transitions.filter_sweep import filter_sweep_mix
from engine.transitions.impact import impact_mix
from engine.transitions.reverse_swell import reverse_swell_mix
from engine.transitions.tape_stop import tape_stop_mix
from engine.transitions.vinyl_brake import vinyl_brake_mix


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

  dispatch = {
    TransitionType.FILTER_SWEEP: filter_sweep_mix,
    TransitionType.ECHO_OUT: echo_out_mix,
    TransitionType.BASS_SWAP: bass_swap_mix,
    TransitionType.TAPE_STOP: tape_stop_mix,
    TransitionType.VINYL_BRAKE: vinyl_brake_mix,
    TransitionType.REVERSE_SWELL: reverse_swell_mix,
    TransitionType.IMPACT: impact_mix,
  }
  handler = dispatch.get(kind)
  if handler is not None:
    return handler(outgoing, incoming)

  return crossfade_segments(outgoing, incoming)
