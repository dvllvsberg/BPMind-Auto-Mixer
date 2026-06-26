import numpy as np
import pytest

from engine.analysis.deep_analyzer import build_energy_map, find_transition_candidates
from engine.domain.enums import AnalysisLevel, TransitionCandidateKind
from engine.domain.models import EnergySegment, Track, TransitionCandidate
from engine.mix_generator.groove_similarity import (
  _transition_pair_similarity,
  groove_similarity,
  has_groove_profile,
)
from engine.mix_generator.transition_points import resolve_play_until


def test_build_energy_map_creates_segments_for_content_region():
  sr = 22050
  duration_sec = 20.0
  y = np.random.default_rng(0).normal(0, 0.2, int(sr * duration_sec)).astype(np.float32)

  segments = build_energy_map(y, sr, content_start=2.0, content_end=18.0, segment_sec=4.0)

  assert len(segments) >= 3
  assert segments[0].start_sec == pytest.approx(2.0, abs=0.1)
  assert segments[-1].end_sec <= 18.1


def test_find_transition_candidates_detects_energy_drop_in_tail():
  energy_map = [
    EnergySegment(start_sec=0.0, end_sec=4.0, energy=-10.0),
    EnergySegment(start_sec=4.0, end_sec=8.0, energy=-9.0),
    EnergySegment(start_sec=8.0, end_sec=12.0, energy=-8.0),
    EnergySegment(start_sec=12.0, end_sec=16.0, energy=-7.0),
    EnergySegment(start_sec=16.0, end_sec=20.0, energy=-16.0),
  ]

  candidates = find_transition_candidates(energy_map, content_start=0.0, content_end=20.0)

  kinds = {candidate.kind for candidate in candidates}
  assert TransitionCandidateKind.ENERGY_DROP in kinds or TransitionCandidateKind.QUIET in kinds


def test_resolve_play_until_prefers_deep_transition_point():
  track = Track(
    id=1,
    path="/a.mp3",
    title="A",
    artist="",
    duration=100.0,
    file_size=1,
    file_mtime=1.0,
    bpm=70.0,
    content_start_sec=0.0,
    content_end_sec=100.0,
    analysis_level=AnalysisLevel.DEEP,
    transition_candidates=[
      TransitionCandidate(
        id=1,
        track_id=1,
        position_sec=82.0,
        kind=TransitionCandidateKind.OUTRO_START,
        confidence=0.9,
      )
    ],
  )

  play_until = resolve_play_until(track, crossfade_duration=8.0, play_ratio=0.5)

  assert play_until == pytest.approx(82.0)


def test_track_play_ratio_raises_minimum_play_until():
  track = Track(
    id=1,
    path="/a.mp3",
    title="A",
    artist="",
    duration=100.0,
    file_size=1,
    file_mtime=1.0,
    bpm=70.0,
    content_start_sec=0.0,
    content_end_sec=100.0,
    analysis_level=AnalysisLevel.DEEP,
    transition_candidates=[
      TransitionCandidate(
        id=1,
        track_id=1,
        position_sec=62.0,
        kind=TransitionCandidateKind.OUTRO_START,
        confidence=0.9,
      )
    ],
  )

  short = resolve_play_until(track, crossfade_duration=8.0, play_ratio=0.5)
  long = resolve_play_until(track, crossfade_duration=8.0, play_ratio=0.9)

  assert short == pytest.approx(62.0)
  assert long == pytest.approx(90.0)


def test_groove_similarity_is_higher_for_similar_profiles():
  base = [
    EnergySegment(start_sec=0.0, end_sec=4.0, energy=-12.0),
    EnergySegment(start_sec=4.0, end_sec=8.0, energy=-10.0),
    EnergySegment(start_sec=8.0, end_sec=12.0, energy=-8.0),
    EnergySegment(start_sec=12.0, end_sec=16.0, energy=-11.0),
  ]
  current = Track(
    id=1,
    path="/a.mp3",
    title="A",
    artist="",
    duration=16.0,
    file_size=1,
    file_mtime=1.0,
    bpm=70.0,
    analysis_level=AnalysisLevel.DEEP,
    energy_map=base,
  )
  similar = Track(
    id=2,
    path="/b.mp3",
    title="B",
    artist="",
    duration=16.0,
    file_size=1,
    file_mtime=1.0,
    bpm=70.0,
    analysis_level=AnalysisLevel.DEEP,
    energy_map=[
      EnergySegment(start_sec=0.0, end_sec=4.0, energy=-11.5),
      EnergySegment(start_sec=4.0, end_sec=8.0, energy=-9.5),
      EnergySegment(start_sec=8.0, end_sec=12.0, energy=-7.8),
      EnergySegment(start_sec=12.0, end_sec=16.0, energy=-10.5),
    ],
  )
  different = Track(
    id=3,
    path="/c.mp3",
    title="C",
    artist="",
    duration=16.0,
    file_size=1,
    file_mtime=1.0,
    bpm=70.0,
    analysis_level=AnalysisLevel.DEEP,
    energy_map=[
      EnergySegment(start_sec=0.0, end_sec=4.0, energy=-20.0),
      EnergySegment(start_sec=4.0, end_sec=8.0, energy=-8.0),
      EnergySegment(start_sec=8.0, end_sec=12.0, energy=-20.0),
      EnergySegment(start_sec=12.0, end_sec=16.0, energy=-8.0),
    ],
  )

  assert has_groove_profile(current)
  assert groove_similarity(current, similar) > groove_similarity(current, different)


def test_transition_pair_prefers_matching_outro_intro():
  outgoing = [
    EnergySegment(start_sec=0.0, end_sec=4.0, energy=-14.0),
    EnergySegment(start_sec=4.0, end_sec=8.0, energy=-12.0),
    EnergySegment(start_sec=8.0, end_sec=12.0, energy=-10.0),
    EnergySegment(start_sec=12.0, end_sec=16.0, energy=-9.0),
    EnergySegment(start_sec=16.0, end_sec=20.0, energy=-8.0),
  ]
  good_next = [
    EnergySegment(start_sec=0.0, end_sec=4.0, energy=-8.5),
    EnergySegment(start_sec=4.0, end_sec=8.0, energy=-9.0),
    EnergySegment(start_sec=8.0, end_sec=12.0, energy=-11.0),
    EnergySegment(start_sec=12.0, end_sec=16.0, energy=-13.0),
  ]
  bad_next = [
    EnergySegment(start_sec=0.0, end_sec=4.0, energy=-20.0),
    EnergySegment(start_sec=4.0, end_sec=8.0, energy=-19.0),
    EnergySegment(start_sec=8.0, end_sec=12.0, energy=-17.0),
    EnergySegment(start_sec=12.0, end_sec=16.0, energy=-16.0),
  ]

  def _track(energy_map, track_id: int) -> Track:
    return Track(
      id=track_id,
      path=f"/{track_id}.mp3",
      title=str(track_id),
      artist="",
      duration=20.0,
      file_size=1,
      file_mtime=1.0,
      bpm=70.0,
      analysis_level=AnalysisLevel.DEEP,
      energy_map=energy_map,
    )

  current = _track(outgoing, 1)
  assert _transition_pair_similarity(current, _track(good_next, 2)) > _transition_pair_similarity(
    current, _track(bad_next, 3)
  )
