from __future__ import annotations

import numpy as np

from engine.transitions.crossfade import crossfade_segments
from engine.transitions.dsp_utils import apply_echo_tail


def reverse_swell_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """Упрощённый reverse-reverb: короткий реверс головы входящего + crossfade."""
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  if incoming.ndim == 1:
    incoming = incoming.reshape(-1, 1)

  head_len = max(min(len(incoming) // 4, len(incoming)), 1)
  if head_len < 16:
    return crossfade_segments(outgoing, incoming, incoming_delay=0.45)

  head = incoming[:head_len]
  reversed_head = head[::-1].copy()
  swell = apply_echo_tail(reversed_head, delay_fraction=0.14, feedback=0.52)
  fade = np.linspace(0.75, 0.0, len(swell), dtype=np.float32).reshape(-1, 1)

  enriched = incoming.astype(np.float32, copy=True)
  enriched[: len(swell)] += swell * fade * 0.72
  return crossfade_segments(outgoing, enriched, incoming_delay=0.45)
