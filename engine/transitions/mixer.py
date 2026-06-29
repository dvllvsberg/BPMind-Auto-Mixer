from __future__ import annotations

import numpy as np

from engine.domain.enums import TransitionType
from engine.transitions.junction import render_transition_junction


def mix_transition_segments(
  transition_type: TransitionType,
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> np.ndarray:
  return render_transition_junction(transition_type, outgoing, incoming).as_overlap_chunk()
