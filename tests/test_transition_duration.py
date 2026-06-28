from __future__ import annotations

from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, Track
from engine.mix_generator.transition_points import planning_crossfade_sec
from engine.transitions.context import build_transition_context
from engine.transitions.duration import (
  bar_duration_sec,
  compute_transition_duration_sec,
)
from engine.transitions.modes import TransitionMode
from engine.transitions.planner import TransitionPlanConfig, TransitionPlanner


def _track(
  track_id: int,
  *,
  bpm: float = 120.0,
  duration: float = 180.0,
) -> Track:
  return Track(
    id=track_id,
    path=f"/t{track_id}.wav",
    title=f"T{track_id}",
    artist="",
    duration=duration,
    file_size=1,
    file_mtime=1.0,
    bpm=bpm,
    analysis_level=AnalysisLevel.QUICK,
  )


def _session(*track_ids: int, play_until: float = 150.0) -> MixSession:
  return MixSession(
    tracks=[
      MixSessionTrack(track_id=track_id, play_from_sec=0.0, play_until_sec=play_until)
      for track_id in track_ids
    ],
    transitions=[],
    start_mode=StartMode.PEAK,
  )


def test_vinyl_shorter_than_smooth_at_same_bpm():
  track_a = _track(1, bpm=70.0)
  track_b = _track(2, bpm=70.0)
  ctx = build_transition_context(track_a, track_b)
  item = MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=150.0)

  smooth = compute_transition_duration_sec(
    TransitionType.SMOOTH_BLEND,
    ctx,
    outgoing_item=item,
    outgoing_track=track_a,
    play_until_sec=150.0,
    global_cap_sec=8.0,
  )
  vinyl = compute_transition_duration_sec(
    TransitionType.VINYL_BRAKE,
    ctx,
    outgoing_item=item,
    outgoing_track=track_a,
    play_until_sec=150.0,
    global_cap_sec=8.0,
  )

  assert smooth > vinyl
  assert vinyl <= 8.0 * 0.4 + 0.01


def test_auto_duration_respects_global_cap():
  track_a = _track(1, bpm=60.0)
  track_b = _track(2, bpm=60.0)
  ctx = build_transition_context(track_a, track_b)
  item = MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=200.0)

  duration = compute_transition_duration_sec(
    TransitionType.SMOOTH_BLEND,
    ctx,
    outgoing_item=item,
    outgoing_track=track_a,
    play_until_sec=200.0,
    global_cap_sec=6.0,
  )

  assert duration <= 6.0


def test_auto_duration_disabled_uses_global():
  track_a = _track(1, bpm=120.0)
  track_b = _track(2, bpm=120.0)
  ctx = build_transition_context(track_a, track_b)
  item = MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=150.0)

  duration = compute_transition_duration_sec(
    TransitionType.VINYL_BRAKE,
    ctx,
    outgoing_item=item,
    outgoing_track=track_a,
    play_until_sec=150.0,
    global_cap_sec=8.0,
    auto_duration=False,
  )

  assert duration == 8.0


def test_planner_assigns_per_profile_durations():
  session = _session(1, 2, 3, play_until=150.0)
  tracks_by_id = {
    1: _track(1, bpm=70.0),
    2: _track(2, bpm=72.0),
    3: _track(3, bpm=74.0),
  }
  planner = TransitionPlanner()
  plan = planner.plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(
      mode=TransitionMode.FIXED,
      fixed_profile=TransitionType.SMOOTH_BLEND,
      crossfade_duration_sec=8.0,
    ),
  )
  vinyl_plan = planner.plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(
      mode=TransitionMode.FIXED,
      fixed_profile=TransitionType.VINYL_BRAKE,
      crossfade_duration_sec=8.0,
    ),
  )

  assert len(plan) == 2
  assert all(item.crossfade_duration_sec > 0 for item in plan)
  assert vinyl_plan[0].crossfade_duration_sec < plan[0].crossfade_duration_sec


def test_planner_cut_has_zero_duration():
  session = _session(1, 2)
  tracks_by_id = {1: _track(1), 2: _track(2)}
  plan = TransitionPlanner().plan(
    session,
    tracks_by_id,
    TransitionPlanConfig(
      mode=TransitionMode.FIXED,
      fixed_profile=TransitionType.CUT,
      crossfade_duration_sec=8.0,
    ),
  )
  assert plan[0].crossfade_duration_sec == 0.0


def test_duration_snaps_to_half_bar():
  bar = bar_duration_sec(120.0)
  track_a = _track(1, bpm=120.0)
  track_b = _track(2, bpm=120.0)
  ctx = build_transition_context(track_a, track_b)
  item = MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=150.0)

  duration = compute_transition_duration_sec(
    TransitionType.IMPACT,
    ctx,
    outgoing_item=item,
    outgoing_track=track_a,
    play_until_sec=150.0,
    global_cap_sec=8.0,
  )

  bars = duration / bar
  assert abs(bars - round(bars * 2) / 2) < 0.01


def test_planning_crossfade_sec_is_at_least_ten():
  assert planning_crossfade_sec(4.0) == 10.0
  assert planning_crossfade_sec(12.0) == 12.0
