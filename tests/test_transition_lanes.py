from __future__ import annotations

import numpy as np
import pytest

from engine.domain.enums import TransitionType
from engine.domain.models import PlannedTransition
from engine.transitions.junction import (
  render_transition_junction,
  write_junction_debug_wavs,
)
from engine.transitions.lanes import (
  JunctionLane,
  mix_lanes,
  render_staged_blend,
)
from engine.transitions.overlap_utils import staged_tail_blend
from engine.transitions.playback_rules import planned_incoming_main_skip_sec


def test_mix_lanes_sums_weighted_sources():
  audio_a = np.ones((4, 2), dtype=np.float32)
  audio_b = np.full((4, 2), 2.0, dtype=np.float32)
  gain_a = np.array([1.0, 0.5, 0.0, 0.0], dtype=np.float32).reshape(-1, 1)
  gain_b = np.array([0.0, 0.5, 1.0, 1.0], dtype=np.float32).reshape(-1, 1)

  mixed = mix_lanes(
    [
      JunctionLane(audio_a, gain_a),
      JunctionLane(audio_b, gain_b),
    ]
  )

  assert mixed[0, 0] == pytest.approx(1.0)
  assert mixed[1, 0] == pytest.approx(1.5)
  assert mixed[2, 0] == pytest.approx(2.0)


def test_render_staged_blend_matches_legacy_staged_tail_blend():
  rng = np.random.default_rng(42)
  outgoing = rng.standard_normal((800, 2)).astype(np.float32)
  incoming = rng.standard_normal((800, 2)).astype(np.float32)

  legacy = staged_tail_blend(
    outgoing,
    incoming,
    incoming_blend_sec=0.9,
    incoming_fade_power=0.62,
    outgoing_fade_power=0.88,
  )
  lanes = render_staged_blend(
    outgoing,
    incoming,
    incoming_blend_sec=0.9,
    incoming_fade_power=0.62,
    outgoing_fade_power=0.88,
    pin_tail_to_incoming=False,
  ).as_overlap_chunk()

  assert np.allclose(legacy, lanes, atol=1e-6)


def test_planned_skip_matches_junction_render_for_reverse():
  length = 44100 * 4
  rng = np.random.default_rng(21)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.4
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.4

  transition = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.REVERSE_SWELL,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  render = render_transition_junction(TransitionType.REVERSE_SWELL, outgoing, incoming)
  assert render.incoming_main_skip_sec == pytest.approx(
    planned_incoming_main_skip_sec(transition),
    abs=1e-4,
  )
  assert len(render.lanes) == 3
  assert render.lane_labels == ("outgoing", "reverse", "incoming")


def test_reverse_junction_handoff_welds_to_main_skip():
  from engine.transitions.reverse_swell_motor import (
    reverse_forward_lead_frames,
    reverse_handoff_frames,
    reverse_incoming_skip_sec,
    reverse_pivot_index,
  )

  length = 44100 * 4
  rng = np.random.default_rng(57)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.4
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.4

  transition = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.REVERSE_SWELL,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  render = render_transition_junction(TransitionType.REVERSE_SWELL, outgoing, incoming)
  assert render.incoming_main_skip_sec == pytest.approx(
    planned_incoming_main_skip_sec(transition),
    abs=1e-4,
  )
  assert render.incoming_main_skip_sec == pytest.approx(
    reverse_incoming_skip_sec(crossfade_duration_sec=8.0),
    abs=1e-4,
  )

  swell_len = min(int(1.8 * 44100), len(incoming))
  handoff = reverse_handoff_frames(swell_len=swell_len)
  lead = reverse_forward_lead_frames(overlap=len(incoming))
  pivot = reverse_pivot_index(handoff_frames=handoff, head_len=len(incoming), seam_frames=lead)
  assert np.allclose(render.overlap_audio[-1], incoming[pivot], atol=1e-3)

  fwd = next(audio for label, audio in render.lane_outputs() if label == "incoming")
  assert float(np.max(np.abs(fwd[-handoff:]))) > 0.01
  assert float(np.max(np.abs((fwd * render.lanes[2].gain.reshape(-1, 1))[-handoff:]))) > 0.01


def test_reverse_junction_skips_silent_head_prefix():
  from engine.transitions.reverse_swell_motor import (
    reverse_head_entry_frames,
    reverse_skip_frames,
  )

  length = 44100 * 2
  rng = np.random.default_rng(91)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.35
  incoming = np.zeros((length, 2), dtype=np.float32)
  silent = int(0.05 * 44100)
  incoming[silent:] = rng.standard_normal((length - silent, 2)).astype(np.float32) * 0.35

  render = render_transition_junction(TransitionType.REVERSE_SWELL, outgoing, incoming)
  entry = reverse_head_entry_frames(incoming)
  effective_overlap = min(length, max(0, len(incoming) - entry))
  skip_frames = entry + reverse_skip_frames(overlap=effective_overlap)
  assert render.incoming_main_skip_sec == pytest.approx(skip_frames / 44100, abs=1e-4)
  assert np.allclose(render.overlap_audio[-1], incoming[skip_frames], atol=1e-3)

  fwd_lane = render.lanes[2].audio * render.lanes[2].gain
  handoff = int(0.14 * 44100)
  assert float(np.sqrt(np.mean(fwd_lane[-handoff:] ** 2))) > 0.02


def test_reverse_junction_reverse_lane_dominates_at_swell():
  length = 44100 * 6
  rng = np.random.default_rng(55)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.4
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.4

  render = render_transition_junction(TransitionType.REVERSE_SWELL, outgoing, incoming)
  rev = next(audio for label, audio in render.lane_outputs() if label == "reverse")

  swell_len = min(int(1.8 * 44100), len(rev))
  swell_start = len(rev) - swell_len
  rev_peak = float(np.max(np.abs(rev[swell_start + swell_len // 3 : swell_start + swell_len])))
  assert rev_peak > 0.02


def test_reverse_junction_no_hole_at_swell_start():
  length = 44100 * 4
  rng = np.random.default_rng(56)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.35
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.35

  render = render_transition_junction(TransitionType.REVERSE_SWELL, outgoing, incoming)
  mixed = render.overlap_audio

  swell_len = min(int(1.8 * 44100), len(mixed))
  swell_start = len(mixed) - swell_len
  window = min(800, swell_len // 4)
  before = float(np.sqrt(np.mean(mixed[swell_start - window : swell_start] ** 2)))
  at = float(np.sqrt(np.mean(mixed[swell_start : swell_start + window] ** 2)))
  assert at >= before * 0.55


def test_impact_junction_has_cinematic_fx_lane():
  length = 44100 * 2
  rng = np.random.default_rng(33)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.4
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.4

  render = render_transition_junction(TransitionType.IMPACT, outgoing, incoming)
  assert len(render.lanes) == 3
  assert render.lane_labels == ("outgoing", "incoming", "cinematic")

  fx_only = next(audio for label, audio in render.lane_outputs() if label == "cinematic")
  assert float(np.max(np.abs(fx_only))) > 0.02

  # Энергия в низах (braaam/bass drop), не свист в верхах.
  spectrum = np.abs(np.fft.rfft(fx_only[:, 0]))
  freqs = np.fft.rfftfreq(len(fx_only), d=1.0 / 44100.0)
  low = float(np.sum(spectrum[freqs < 180.0] ** 2))
  high = float(np.sum(spectrum[freqs > 900.0] ** 2))
  assert low > high * 2.5


def test_impact_start_without_volume_cliff():
  length = 44100
  rng = np.random.default_rng(44)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.35
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.35

  render = render_transition_junction(TransitionType.IMPACT, outgoing, incoming)
  mixed = render.overlap_audio
  window = 400
  start_rms = float(np.sqrt(np.mean(mixed[:window] ** 2)))
  ref_rms = float(np.sqrt(np.mean(outgoing[:window] ** 2)))
  assert start_rms >= ref_rms * 0.45


def test_impact_dip_zone_is_short_not_half_overlap():
  from engine.transitions.impact_motor import IMPACT_DIP_SEC, impact_junction_frame

  overlap = 44100 * 6
  junction = impact_junction_frame(overlap)
  dip_sec = (overlap - junction) / 44100.0
  assert dip_sec <= IMPACT_DIP_SEC + 0.15


def test_impact_outgoing_gain_starts_at_unity():
  from engine.transitions.impact_motor import build_impact_crossfade_gains, impact_junction_frame

  overlap = 8000
  junction = impact_junction_frame(overlap)
  out_gain, in_gain = build_impact_crossfade_gains(overlap, junction)
  assert float(out_gain[0, 0]) == pytest.approx(1.0)
  assert float(in_gain[0, 0]) == pytest.approx(0.0)
  assert float(out_gain[junction - 1, 0]) == pytest.approx(1.0, abs=0.02)


def test_write_junction_debug_wavs(tmp_path):
  length = 2000
  rng = np.random.default_rng(1)
  outgoing = rng.standard_normal((length, 2)).astype(np.float32) * 0.3
  incoming = rng.standard_normal((length, 2)).astype(np.float32) * 0.3

  render = render_transition_junction(TransitionType.IMPACT, outgoing, incoming)
  paths = write_junction_debug_wavs(render, tmp_path, prefix="test")

  assert len(paths) >= 4
  assert (tmp_path / "test_mix.wav").exists()
  assert (tmp_path / "test_cinematic.wav").exists()
