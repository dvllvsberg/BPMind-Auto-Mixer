from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import VINYL_BRAKE_SR, vinyl_rewind_brake_outgoing

# Входящий трек — только в конце overlap (фикс. окно), иначе «вперёд» накладывается на brake.
VINYL_INCOMING_BLEND_SEC = 0.5


def vinyl_brake_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  if outgoing.ndim == 1:
    outgoing = outgoing.reshape(-1, 1)
  if incoming.ndim == 1:
    incoming = incoming.reshape(-1, 1)

  overlap = min(len(outgoing), len(incoming))
  if overlap == 0:
    channels = outgoing.shape[1] if outgoing.ndim > 1 else 1
    return np.zeros((0, channels), dtype=np.float32)

  tail = outgoing[-overlap:]
  head = incoming[:overlap]
  scratched = vinyl_rewind_brake_outgoing(tail)

  blend_frames = min(int(VINYL_INCOMING_BLEND_SEC * VINYL_BRAKE_SR), overlap)
  solo_frames = max(0, overlap - blend_frames)

  mixed = scratched.astype(np.float32, copy=True)
  if blend_frames <= 0:
    return mixed

  ramp = np.linspace(0.0, 1.0, blend_frames, dtype=np.float32).reshape(-1, 1)
  fade_in = np.power(ramp, 0.72)
  fade_out = np.power(1.0 - ramp, 1.05)
  mixed[solo_frames:] = (
    scratched[solo_frames:] * fade_out + head[solo_frames:] * fade_in
  ).astype(np.float32, copy=False)

  return mixed
