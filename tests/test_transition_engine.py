import json

import numpy as np

from engine.domain.enums import AnalysisLevel, StartMode, TransitionCandidateKind, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, Track, TransitionCandidate
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
  chosen = decide_profile(
    ctx,
    recent_uses_by_type={
      TransitionType.SMOOTH_BLEND: 3,
      TransitionType.FILTER_SWEEP: 0,
      TransitionType.CUT: 0,
    },
  )
  assert chosen is TransitionType.FILTER_SWEEP


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
