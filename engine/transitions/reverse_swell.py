from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import reverse_swell_at_junction, reverse_swell_outgoing_tail
from engine.transitions.lanes import (
  JunctionLane,
  JunctionRender,
  align_junction,
  empty_junction_render,
  mix_lanes,
  pin_overlap_tail,
)
from engine.transitions.overlap_utils import OVERLAP_SR
from engine.transitions.reverse_swell_motor import (
  REVERSE_SWELL_SEC,
  build_reverse_full_gains,
  reverse_forward_lead_frames,
  reverse_head_entry_frames,
  reverse_incoming_skip_sec,
  reverse_pivot_index,
  reverse_skip_frames,
  reverse_swell_frames,
  reverse_swell_start_frame,
)

__all__ = [
  "REVERSE_SWELL_SEC",
  "render_reverse_swell_junction",
  "reverse_incoming_skip_sec",
  "reverse_swell_mix",
]


def render_reverse_swell_junction(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  """
  Отражение head[0:N] → …3 2 1, handoff → 2 3…, main body с head[1+handoff].

  Три дорожки на overlap:
  - outgoing — solo A, затем fade;
  - reverse — reversed фрагмент;
  - incoming — forward handoff в хвосте junction (слепка с main body).
  """
  if outgoing.size == 0:
    return JunctionRender(
      incoming.astype(np.float32, copy=False),
      incoming_main_skip_sec=0.0,
    )
  if incoming.size == 0:
    return JunctionRender(outgoing.astype(np.float32, copy=False))

  entry = reverse_head_entry_frames(incoming)
  head = incoming[entry:].astype(np.float32, copy=False)

  tail, head, overlap = align_junction(outgoing, head)
  if overlap == 0:
    return empty_junction_render(tail.shape[1] if tail.size else 2)

  swell_len = reverse_swell_frames(overlap=overlap)
  swell_start = reverse_swell_start_frame(overlap)

  if swell_len <= 0:
    return JunctionRender(tail.astype(np.float32, copy=False), incoming_main_skip_sec=0.0)

  out_gain, rev_gain, fwd_gain, handoff = build_reverse_full_gains(overlap)
  skip_frames = reverse_skip_frames(overlap=overlap)
  skip_sec = (entry + skip_frames) / OVERLAP_SR

  outgoing_audio = reverse_swell_outgoing_tail(tail)
  reverse_audio = np.zeros_like(tail)
  swell = reverse_swell_at_junction(head, swell_sec=REVERSE_SWELL_SEC)
  reverse_audio[swell_start : swell_start + swell_len] = swell[:swell_len]

  forward_audio = np.zeros_like(tail)
  if skip_frames > 1:
    forward_slice = head[1:skip_frames]
    if len(forward_slice) > 0:
      forward_audio[-len(forward_slice) :] = forward_slice

  lanes = (
    JunctionLane(outgoing_audio, out_gain.reshape(-1, 1)),
    JunctionLane(reverse_audio, rev_gain.reshape(-1, 1)),
    JunctionLane(forward_audio, fwd_gain.reshape(-1, 1)),
  )
  mixed = mix_lanes(list(lanes))

  pivot_index = reverse_pivot_index(
    handoff_frames=handoff,
    head_len=len(head),
    seam_frames=reverse_forward_lead_frames(overlap=overlap),
  )
  mixed = pin_overlap_tail(mixed, incoming[entry + pivot_index])

  return JunctionRender(
    overlap_audio=mixed,
    incoming_main_skip_sec=skip_sec,
    lanes=lanes,
    lane_labels=("outgoing", "reverse", "incoming"),
  )


def reverse_swell_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_reverse_swell_junction(outgoing, incoming).as_overlap_chunk()
