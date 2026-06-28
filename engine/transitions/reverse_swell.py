from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import reverse_swell_at_junction
from engine.transitions.overlap_utils import align_overlap, sec_to_frames

REVERSE_SWELL_SEC = 1.8


def reverse_incoming_skip_sec(*, crossfade_duration_sec: float) -> float:
  return min(REVERSE_SWELL_SEC, crossfade_duration_sec)


def reverse_swell_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  """
  Reverse overlay с непрерывной энергией: reverse в первой половине swell,
  forward B нарастает во второй; overlap[-1] = head[swell_len-1].
  """
  if outgoing.size == 0:
    return incoming.astype(np.float32, copy=False)
  if incoming.size == 0:
    return outgoing.astype(np.float32, copy=False)

  tail, head, overlap = align_overlap(outgoing, incoming)
  if overlap == 0:
    return np.zeros((0, tail.shape[1]), dtype=np.float32)

  swell_len = min(sec_to_frames(REVERSE_SWELL_SEC), overlap)
  swell_start = max(0, overlap - swell_len)

  mixed = tail.astype(np.float32, copy=True)
  if swell_len <= 0:
    return mixed

  swell = reverse_swell_at_junction(head, swell_sec=REVERSE_SWELL_SEC)
  t = np.linspace(0.0, 1.0, swell_len, dtype=np.float32)

  # A: полный до ~12% swell, затем cosine fade.
  a_gain = np.where(
    t < 0.12,
    1.0,
    0.5 * (1.0 + np.cos(np.pi * np.clip((t - 0.12) / 0.88, 0.0, 1.0))),
  )
  # Reverse: колокол в первых ~72% swell.
  rev_t = np.clip(t / 0.72, 0.0, 1.0)
  rev_sin = np.clip(np.sin(np.pi * rev_t), 0.0, 1.0) ** 0.9
  rev_tail = np.clip((0.78 - t) / 0.28, 0.0, 1.0) ** 0.65
  rev_gain = rev_sin * rev_tail
  # Forward B: с ~38% swell до конца (комплементарно reverse, без «дыр»).
  fwd_t = np.clip((t - 0.38) / 0.62, 0.0, 1.0)
  fwd_gain = 0.5 * (1.0 - np.cos(np.pi * fwd_t))

  a_col = a_gain.reshape(-1, 1)
  rev_col = rev_gain.reshape(-1, 1)
  fwd_col = fwd_gain.reshape(-1, 1)

  zone = (
    tail[swell_start:] * a_col
    + swell[:swell_len] * rev_col * 1.05
    + head[:swell_len] * fwd_col
  ).astype(np.float32, copy=False)
  mixed[swell_start:] = zone
  mixed[-1] = head[swell_len - 1]
  return mixed
