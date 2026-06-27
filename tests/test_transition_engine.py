import json

import numpy as np
import pytest

from engine.domain.enums import AnalysisLevel, StartMode, TransitionCandidateKind, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track, TransitionCandidate
from engine.domain.models import EnergySegment
from engine.mix_generator.session_store import load_mix_session
from engine.transitions.display import summarize_session_transitions
from engine.transitions.context import build_transition_context
from engine.transitions.mixer import mix_transition_segments
from engine.transitions.modes import TransitionMode
from engine.transitions.planner import TransitionPlanConfig, TransitionPlanner
from engine.transitions.profiles import decide_profile


def _track(track_id: int, *, bpm: float, loudness: float = -18.0) -> Track:
  return Track(
    id=track_id,
    path=f"/music/{track_id}.mp3",
    title=f"T{track_id}",
    artist="Test",
    duration=180.0,
    file_size=1000,
    file_mtime=1.0,
    bpm=bpm,
    loudness_avg=loudness,
    loudness_peak=loudness + 3,
    content_start_sec=0.0,
    content_end_sec=180.0,
    analysis_level=AnalysisLevel.DEEP,
  )


def test_transition_type_parse_legacy_crossfade():
  assert TransitionType.parse("crossfade") is TransitionType.SMOOTH_BLEND


def test_mixer_smooth_blend_matches_lengths():
  outgoing = np.ones((100, 2), dtype=np.float32)
  incoming = np.zeros((100, 2), dtype=np.float32)
  mixed = mix_transition_segments(TransitionType.SMOOTH_BLEND, outgoing, incoming)
  assert mixed.shape == (100, 2)
  assert mixed[0, 0] == 1.0
  assert mixed[-1, 0] == 0.0


def test_mixer_cut_concatenates():
  outgoing = np.ones((50, 2), dtype=np.float32)
  incoming = np.full((30, 2), 2.0, dtype=np.float32)
  mixed = mix_transition_segments(TransitionType.CUT, outgoing, incoming)
  assert mixed.shape == (80, 2)
  assert mixed[49, 0] == 1.0
  assert mixed[50, 0] == 2.0


def test_auto_mode_prefers_smooth_for_ideal_pair():
  track_a = _track(1, bpm=120.0, loudness=-18.0)
  track_b = _track(2, bpm=121.0, loudness=-18.5)
  ctx = build_transition_context(track_a, track_b)
  chosen = decide_profile(ctx, recent_uses_by_type={})
  assert chosen is TransitionType.SMOOTH_BLEND


def test_streak_of_smooth_boosts_filter():
  track_a = _track(1, bpm=120.0, loudness=-14.0)
  track_b = _track(2, bpm=122.0, loudness=-20.0)
  recent = (
    TransitionType.SMOOTH_BLEND,
    TransitionType.SMOOTH_BLEND,
    TransitionType.SMOOTH_BLEND,
  )
  ctx = build_transition_context(track_a, track_b, recent_profiles=recent)
  recent_uses = {profile.type: 0 for profile in __import__(
    "engine.transitions.profiles", fromlist=["PROFILES_AUTO"]
  ).PROFILES_AUTO}
  recent_uses[TransitionType.SMOOTH_BLEND] = 3
  chosen = decide_profile(ctx, recent_uses_by_type=recent_uses)
  assert chosen is TransitionType.FILTER_SWEEP


def _energy_map() -> list[EnergySegment]:
  return [
    EnergySegment(start_sec=0.0, end_sec=60.0, energy=0.4),
    EnergySegment(start_sec=60.0, end_sec=120.0, energy=0.55),
    EnergySegment(start_sec=120.0, end_sec=180.0, energy=0.45),
  ]


def test_auto_mode_picks_bass_swap_for_close_bpm():
  track_a = _track(1, bpm=120.0, loudness=-18.0)
  track_b = _track(2, bpm=121.5, loudness=-18.0)
  track_a.energy_map = _energy_map()
  track_b.energy_map = _energy_map()
  ctx = build_transition_context(track_a, track_b)
  chosen = decide_profile(ctx, recent_uses_by_type={})
  assert chosen is TransitionType.BASS_SWAP


def test_auto_mode_picks_impact_when_incoming_louder():
  track_a = _track(1, bpm=120.0, loudness=-20.0)
  track_b = _track(2, bpm=122.0, loudness=-14.0)
  ctx = build_transition_context(track_a, track_b)
  chosen = decide_profile(ctx, recent_uses_by_type={})
  assert chosen is TransitionType.IMPACT


def test_new_profiles_preserve_overlap_length():
  outgoing = np.linspace(1.0, 0.0, 200, dtype=np.float32).reshape(-1, 1)
  incoming = np.linspace(0.0, 1.0, 200, dtype=np.float32).reshape(-1, 1)
  for profile in (
    TransitionType.ECHO_OUT,
    TransitionType.BASS_SWAP,
    TransitionType.TAPE_STOP,
    TransitionType.VINYL_BRAKE,
    TransitionType.REVERSE_SWELL,
    TransitionType.IMPACT,
  ):
    mixed = mix_transition_segments(profile, outgoing, incoming)
    assert mixed.shape == (200, 1), profile.value


def test_echo_out_end_matches_incoming_for_seamless_main_body():
  incoming = np.random.default_rng(6).standard_normal((700, 2)).astype(np.float32)
  outgoing = np.random.default_rng(7).standard_normal((700, 2)).astype(np.float32)
  mixed = mix_transition_segments(TransitionType.ECHO_OUT, outgoing, incoming)
  assert np.allclose(mixed[-1], incoming[-1], atol=1e-5)


def test_tape_stop_ends_lower_pitch_than_start():
  from engine.transitions.tape_stop import tape_motor_stop_outgoing

  length = 4000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  channel = np.sin(t * 80 * np.pi).reshape(-1, 1).astype(np.float32)
  processed = tape_motor_stop_outgoing(channel)

  zc_start = np.sum(np.diff(np.sign(processed[: length // 4, 0])) != 0)
  zc_end = np.sum(np.diff(np.sign(processed[-length // 4 :, 0])) != 0)
  assert zc_end < zc_start * 0.75


def test_tape_motor_rate_curves_are_smooth_without_steps():
  from engine.transitions.tape_stop import _motor_rate_start, _motor_rate_stop

  progress = np.linspace(0.0, 1.0, 2000, dtype=np.float32)
  stop_rates = _motor_rate_stop(progress)
  start_rates = _motor_rate_start(progress)

  assert np.all(np.diff(stop_rates) <= 1e-5)
  assert np.all(np.diff(start_rates) >= -1e-5)
  assert float(np.max(np.abs(np.diff(stop_rates, 2)))) < 0.06
  assert float(np.max(np.abs(np.diff(start_rates, 2)))) < 0.03
  # подъём в первой четверти быстрее, чем линейный sin
  quarter = len(progress) // 4
  assert float(start_rates[quarter]) > float(np.sin(0.25 * (np.pi * 0.5)))


def test_tape_stop_differs_from_smooth_blend():
  length = 8000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.stack([np.sin(t * 48 * np.pi), np.sin(t * 48 * np.pi)], axis=1)
  incoming = np.stack([np.sin(t * 40 * np.pi), np.sin(t * 40 * np.pi)], axis=1)
  smooth = mix_transition_segments(TransitionType.SMOOTH_BLEND, outgoing, incoming)
  tape = mix_transition_segments(TransitionType.TAPE_STOP, outgoing, incoming)
  assert float(np.mean(np.abs(smooth - tape))) > 0.02


def test_tape_motor_stop_never_stalls_on_same_samples():
  from engine.transitions.tape_stop import tape_motor_stop_outgoing

  length = 4000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.sin(t * 60 * np.pi).reshape(-1, 1).astype(np.float32)
  processed = tape_motor_stop_outgoing(outgoing)
  assert np.isfinite(processed).all()
  diffs = np.abs(np.diff(processed[:, 0]))
  assert int(np.sum(diffs < 1e-6)) < length * 0.02


def test_vinyl_nudge_duration_is_wall_clock_not_fraction():
  from engine.transitions.dsp_utils import _vinyl_nudge_samples, _vinyl_platter_source_indices

  assert _vinyl_nudge_samples(400_000) == _vinyl_nudge_samples(800_000)
  for length in (400_000, 800_000):
    nudge = _vinyl_nudge_samples(length)
    progress = np.linspace(0.0, 1.0, length, dtype=np.float32)
    indices = _vinyl_platter_source_indices(progress, length)
    body = indices[: length - nudge]
    assert np.all(np.diff(body) >= -1e-5)


def test_vinyl_brake_incoming_only_in_tail_window():
  from engine.transitions.vinyl_brake import VINYL_INCOMING_BLEND_SEC, vinyl_brake_mix

  overlap = int(8.0 * 44100)
  solo = overlap - min(int(VINYL_INCOMING_BLEND_SEC * 44100), overlap)
  outgoing = np.random.default_rng(1).standard_normal((overlap, 2)).astype(np.float32)
  incoming = np.full((overlap, 2), 2.0, dtype=np.float32)
  mixed = vinyl_brake_mix(outgoing, incoming)
  assert not np.allclose(mixed[:solo], 2.0, atol=0.05)
  assert float(np.mean(mixed[solo:])) > float(np.mean(mixed[: max(solo // 2, 1)])) + 0.1


def test_vinyl_brake_single_backward_segment():
  from engine.transitions.dsp_utils import _vinyl_platter_source_indices

  progress = np.linspace(0.0, 1.0, 4000, dtype=np.float32)
  indices = _vinyl_platter_source_indices(progress, 4000)
  decreasing = np.diff(indices) < -1e-6
  runs: list[int] = []
  in_run = False
  for value in decreasing:
    if value and not in_run:
      runs.append(1)
      in_run = True
    elif not value:
      in_run = False
  assert len(runs) == 1


def test_vinyl_brake_slows_pitch_without_stutter():
  from engine.transitions.dsp_utils import vinyl_rewind_brake_outgoing

  length = 8000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.sin(t * 60 * np.pi).reshape(-1, 1).astype(np.float32)
  processed = vinyl_rewind_brake_outgoing(outgoing)
  zc_start = np.sum(np.diff(np.sign(processed[: length // 4, 0])) != 0)
  zc_end = np.sum(np.diff(np.sign(processed[-length // 4 :, 0])) != 0)
  assert zc_end < zc_start * 0.8
  stutter = int(np.sum(np.abs(np.diff(processed[:, 0])) < 1e-6))
  assert stutter < length * 0.015


def test_tape_stop_and_vinyl_brake_sound_different():
  length = 4000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.stack([np.sin(t * 50 * np.pi), np.sin(t * 50 * np.pi)], axis=1)
  incoming = np.stack([np.sin(t * 44 * np.pi), np.sin(t * 44 * np.pi)], axis=1)
  tape = mix_transition_segments(TransitionType.TAPE_STOP, outgoing, incoming)
  vinyl = mix_transition_segments(TransitionType.VINYL_BRAKE, outgoing, incoming)
  assert tape.shape == vinyl.shape
  assert float(np.mean(np.abs(tape - vinyl))) > 0.02


def test_tape_stop_solo_tail_fades_to_silence():
  from engine.transitions.tape_stop import tape_motor_stop_outgoing

  length = 8000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.stack([np.sin(t * 48 * np.pi), np.sin(t * 48 * np.pi)], axis=1)
  processed = tape_motor_stop_outgoing(outgoing)
  tail = processed[-32:]
  assert float(np.max(np.abs(tail))) < 0.03


def test_tape_motor_start_ramps_up_pitch_and_volume():
  from engine.transitions.tape_stop import tape_motor_start_incoming, tape_motor_stop_outgoing

  length = 8000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  incoming = np.stack([np.sin(t * 48 * np.pi), np.sin(t * 48 * np.pi)], axis=1)
  started = tape_motor_start_incoming(incoming)
  stopped = tape_motor_stop_outgoing(incoming)

  start_pitch = np.sum(np.diff(np.sign(started[: length // 3, 0])) != 0)
  end_pitch = np.sum(np.diff(np.sign(started[-length // 3 :, 0])) != 0)
  assert end_pitch > start_pitch * 1.2
  assert float(np.max(np.abs(started[-32:]))) > float(np.max(np.abs(started[:32]))) * 1.5
  assert float(np.mean(np.abs(started - stopped))) > 0.02


def test_incoming_tape_spin_sec_matches_tape_stop_transition():
  from engine.transitions.playback_rules import (
    TAPE_STOP_SILENCE_SEC,
    incoming_tape_spin_sec,
    outgoing_tape_brake_sec,
    outgoing_tape_tail_sec,
  )

  transition = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.TAPE_STOP,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  brake = outgoing_tape_brake_sec(transition)
  spin = incoming_tape_spin_sec(transition, enable_crossfade=True, incoming_track_id=2)
  assert spin == pytest.approx(brake * 0.5)
  assert outgoing_tape_tail_sec(transition) + spin == pytest.approx(8.0)
  assert outgoing_tape_tail_sec(transition) - brake == pytest.approx(TAPE_STOP_SILENCE_SEC)
  assert incoming_tape_spin_sec(transition, enable_crossfade=True, incoming_track_id=3) == 0.0


def test_tape_stop_tail_has_no_silence_padding_when_gap_zero():
  from engine.transitions.playback_rules import TAPE_STOP_SILENCE_SEC
  from engine.transitions.render_overlap import render_transition_overlap

  assert TAPE_STOP_SILENCE_SEC == 0.0
  transition = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.TAPE_STOP,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  outgoing = np.random.default_rng(3).standard_normal((4000, 2)).astype(np.float32)
  rendered = render_transition_overlap(transition, outgoing, np.zeros((0, 2), dtype=np.float32))
  assert len(rendered) == len(outgoing)


def test_quiet_spin_makeup_boosts_low_level_head():
  from engine.transitions.tape_stop import apply_quiet_spin_makeup

  quiet = np.full((2000, 2), 0.02, dtype=np.float32)
  loud = np.full((2000, 2), 0.25, dtype=np.float32)
  boosted = apply_quiet_spin_makeup(quiet)
  unchanged = apply_quiet_spin_makeup(loud)
  assert float(np.sqrt(np.mean(boosted**2))) > float(np.sqrt(np.mean(quiet**2))) * 1.5
  assert np.allclose(unchanged, loud)


def test_incoming_play_start_skips_crossfade_offset_after_tape_stop():
  from engine.transitions.playback_rules import incoming_play_start_sec

  transition = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.TAPE_STOP,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  assert incoming_play_start_sec(5.0, transition, enable_crossfade=True, incoming_track_id=2) == 5.0
  crossfade = PlannedTransition(
    from_track_id=1,
    to_track_id=2,
    type=TransitionType.CROSSFADE,
    start_at_sec=90.0,
    crossfade_duration_sec=8.0,
  )
  assert incoming_play_start_sec(5.0, crossfade, enable_crossfade=True, incoming_track_id=2) == 13.0


def test_echo_out_differs_from_smooth():
  length = 3000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.stack([np.sin(t * 40 * np.pi), np.sin(t * 40 * np.pi)], axis=1)
  incoming = np.stack([np.sin(t * 35 * np.pi), np.sin(t * 35 * np.pi)], axis=1)
  smooth = mix_transition_segments(TransitionType.SMOOTH_BLEND, outgoing, incoming)
  echoed = mix_transition_segments(TransitionType.ECHO_OUT, outgoing, incoming)
  assert float(np.mean(np.abs(smooth - echoed))) > 0.005


def test_bass_swap_end_matches_incoming_for_seamless_main_body():
  incoming = np.random.default_rng(0).standard_normal((800, 2)).astype(np.float32)
  outgoing = np.random.default_rng(1).standard_normal((800, 2)).astype(np.float32)
  mixed = mix_transition_segments(TransitionType.BASS_SWAP, outgoing, incoming)
  assert np.allclose(mixed[-1], incoming[-1], atol=1e-5)


def test_filter_sweep_end_matches_incoming_for_seamless_main_body():
  incoming = np.random.default_rng(2).standard_normal((600, 2)).astype(np.float32)
  outgoing = np.random.default_rng(3).standard_normal((600, 2)).astype(np.float32)
  mixed = mix_transition_segments(TransitionType.FILTER_SWEEP, outgoing, incoming)
  assert np.allclose(mixed[-1], incoming[-1], atol=1e-5)


def test_impact_end_matches_incoming_for_seamless_main_body():
  incoming = np.random.default_rng(4).standard_normal((500, 2)).astype(np.float32)
  outgoing = np.random.default_rng(5).standard_normal((500, 2)).astype(np.float32)
  mixed = mix_transition_segments(TransitionType.IMPACT, outgoing, incoming)
  assert np.allclose(mixed[-1], incoming[-1], atol=1e-5)


def test_fixed_mode_uses_single_profile():
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=120.0),
      MixSessionTrack(track_id=2, play_from_sec=0.0, play_until_sec=120.0),
    ],
    transitions=[],
    start_mode=StartMode.CALM,
  )
  track_a = _track(1, bpm=120.0)
  track_b = _track(2, bpm=140.0)
  tracks_by_id = {track_a.id: track_a, track_b.id: track_b}
  planner = TransitionPlanner()
  plan = planner.plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(
      mode=TransitionMode.FIXED,
      fixed_profile=TransitionType.CUT,
      crossfade_duration_sec=8.0,
    ),
  )
  assert len(plan) == 1
  assert plan[0].type is TransitionType.CUT
  assert plan[0].crossfade_duration_sec == 0.0


def test_random_mode_is_reproducible_with_seed():
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=100.0),
      MixSessionTrack(track_id=2, play_until_sec=100.0),
      MixSessionTrack(track_id=3, play_until_sec=100.0),
    ],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )
  tracks_by_id = {
    1: _track(1, bpm=100.0),
    2: _track(2, bpm=105.0),
    3: _track(3, bpm=110.0),
  }
  planner = TransitionPlanner()
  first = planner.plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(mode=TransitionMode.RANDOM, seed=7),
  )
  second = planner.plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(mode=TransitionMode.RANDOM, seed=7),
  )
  assert [item.type for item in first] == [item.type for item in second]


def test_session_store_loads_legacy_crossfade_type(tmp_path):
  legacy = {
    "start_mode": "calm",
    "created_at": "2026-01-01T00:00:00",
    "tracks": [
      {"track_id": 1, "play_from_sec": 0.0, "play_until_sec": 90.0},
      {"track_id": 2, "play_from_sec": 0.0, "play_until_sec": 90.0},
    ],
    "transitions": [
      {
        "from_track_id": 1,
        "to_track_id": 2,
        "type": "crossfade",
        "start_at_sec": 90.0,
        "crossfade_duration_sec": 8.0,
      }
    ],
  }
  path = tmp_path / "legacy.json"
  path.write_text(__import__("json").dumps(legacy), encoding="utf-8")
  session = load_mix_session(path)
  assert session.transitions[0].type is TransitionType.SMOOTH_BLEND


def test_filter_sweep_is_audibly_different_from_smooth():
  length = 4000
  t = np.linspace(0.0, 1.0, length, dtype=np.float32)
  outgoing = np.stack([np.sin(t * 80 * np.pi), np.sin(t * 80 * np.pi)], axis=1)
  incoming = np.stack([np.sin(t * 60 * np.pi), np.sin(t * 60 * np.pi)], axis=1)

  smooth = mix_transition_segments(TransitionType.SMOOTH_BLEND, outgoing, incoming)
  filtered = mix_transition_segments(TransitionType.FILTER_SWEEP, outgoing, incoming)

  assert smooth.shape == filtered.shape
  diff = float(np.mean(np.abs(smooth - filtered)))
  assert diff > 0.01


def test_summarize_session_transitions():
  from engine.domain.enums import StartMode
  from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition

  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1),
      MixSessionTrack(track_id=2),
      MixSessionTrack(track_id=3),
    ],
    transitions=[
      PlannedTransition(1, 2, TransitionType.SMOOTH_BLEND, 90.0, 8.0),
      PlannedTransition(2, 3, TransitionType.FILTER_SWEEP, 90.0, 8.0),
    ],
    start_mode=StartMode.WAVE,
  )
  text = summarize_session_transitions(session)
  assert "плавный ×1" in text
  assert "фильтр" in text


def test_quiet_outro_can_shift_toward_filter():
  track_a = _track(1, bpm=120.0)
  track_a.transition_candidates = [
    TransitionCandidate(
      id=1,
      track_id=1,
      position_sec=150.0,
      kind=TransitionCandidateKind.QUIET,
      confidence=0.9,
    )
  ]
  track_b = _track(2, bpm=140.0)
  ctx = build_transition_context(track_a, track_b)
  assert ctx.has_quiet_outro is True
