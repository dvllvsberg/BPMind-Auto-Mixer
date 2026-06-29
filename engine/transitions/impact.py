from __future__ import annotations

import numpy as np

from engine.transitions.dsp_utils import impact_fx_gain, impact_fx_layer
from engine.transitions.impact_motor import (
  build_impact_crossfade_gains,
  impact_junction_frame,
  impact_pitch_down_outgoing,
  impact_snap_up_incoming,
)
from engine.transitions.lanes import (
  JunctionLane,
  JunctionRender,
  align_junction,
  empty_junction_render,
  mix_lanes,
  pin_overlap_tail,
)
from engine.transitions.overlap_utils import OVERLAP_SR


def render_impact_junction(
  outgoing: np.ndarray,
  incoming: np.ndarray,
) -> JunctionRender:
  """
  Киношный impact: A нормально → короткий dip у стыка → snap B + hit.

  Не tape_stop: нет длинного motor-brake на пол-перехода.
  """
  if outgoing.size == 0:
    return JunctionRender(incoming.astype(np.float32, copy=False))
  if incoming.size == 0:
    return JunctionRender(outgoing.astype(np.float32, copy=False))

  tail, head, overlap = align_junction(outgoing, incoming)
  if overlap == 0:
    return empty_junction_render(tail.shape[1] if tail.size else 2)

  channels = tail.shape[1]
  junction = impact_junction_frame(overlap)
  junction_progress = junction / max(overlap - 1, 1)

  pitched_out = impact_pitch_down_outgoing(tail, junction_frame=junction)
  snapped_in = impact_snap_up_incoming(head, junction_frame=junction)

  out_gain, in_gain = build_impact_crossfade_gains(overlap, junction)

  fx_audio = impact_fx_layer(
    overlap,
    channels,
    junction_progress=junction_progress,
  )
  fx_gain = impact_fx_gain(overlap, junction_progress=junction_progress)

  lanes = (
    JunctionLane(pitched_out, out_gain),
    JunctionLane(snapped_in, in_gain),
    JunctionLane(fx_audio, fx_gain),
  )
  mixed = pin_overlap_tail(mix_lanes(list(lanes)), head[-1])

  return JunctionRender(
    overlap_audio=mixed,
    incoming_main_skip_sec=overlap / OVERLAP_SR,
    lanes=lanes,
    lane_labels=("outgoing", "incoming", "cinematic"),
  )


def impact_mix(outgoing: np.ndarray, incoming: np.ndarray) -> np.ndarray:
  return render_impact_junction(outgoing, incoming).as_overlap_chunk()
