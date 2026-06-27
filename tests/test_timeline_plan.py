import pytest

from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.playback.timeline_plan import RegionKind, build_session_timeline


def _track(track_id: int, *, bpm: float = 70.0, duration: float = 100.0, play_from: float = 0.0) -> Track:
  return Track(
    id=track_id,
    path=f"/music/{track_id}.mp3",
    title=f"T{track_id}",
    artist="A",
    duration=duration,
    file_size=1,
    file_mtime=1.0,
    bpm=bpm,
    loudness_avg=-18.0,
    content_start_sec=play_from,
    content_end_sec=duration,
    analysis_level=AnalysisLevel.QUICK,
  )


def test_session_timeline_total_duration_matches_playback_plan():
  tracks = {
    1: _track(1, duration=100.0),
    2: _track(2, duration=120.0, play_from=5.0),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=90.0),
      MixSessionTrack(track_id=2, play_from_sec=5.0, play_until_sec=110.0),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=90.0,
        crossfade_duration_sec=8.0,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  timeline = build_session_timeline(session, tracks)
  assert len(timeline.tracks) == 2
  assert timeline.total_duration_sec > 0
  assert timeline.tracks[0].crossfade_duration_sec == 8.0
  assert any(region.kind == RegionKind.CROSSFADE for region in timeline.tracks[0].regions)


def test_timeline_tape_stop_uses_solo_tail_region_and_full_incoming_start():
  tracks = {
    1: _track(1, duration=100.0),
    2: _track(2, duration=120.0, play_from=5.0),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=90.0),
      MixSessionTrack(track_id=2, play_from_sec=5.0, play_until_sec=110.0),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.TAPE_STOP,
        start_at_sec=90.0,
        crossfade_duration_sec=8.0,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  timeline = build_session_timeline(session, tracks)
  assert any(region.kind == RegionKind.TAPE_STOP for region in timeline.tracks[0].regions)
  assert not any(region.kind == RegionKind.SILENCE for region in timeline.tracks[0].regions)
  assert not any(region.kind == RegionKind.CROSSFADE for region in timeline.tracks[0].regions)
  assert timeline.tracks[1].main_duration_sec == pytest.approx(105.0)
  assert any(region.kind == RegionKind.TAPE_START for region in timeline.tracks[1].regions)


def test_timeline_main_duration_accounts_for_intro_skip(monkeypatch):
  monkeypatch.setattr(
    "engine.playback.timeline_plan.detect_intro_skip_sec",
    lambda *_args, **_kwargs: 4.0,
  )
  tracks = {
    1: _track(1, duration=100.0),
    2: _track(2, duration=120.0, play_from=5.0),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_from_sec=0.0, play_until_sec=90.0),
      MixSessionTrack(track_id=2, play_from_sec=5.0, play_until_sec=110.0),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.TAPE_STOP,
        start_at_sec=90.0,
        crossfade_duration_sec=8.0,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  timeline = build_session_timeline(session, tracks)
  raw_main = 110.0 - 5.0
  assert timeline.tracks[1].main_duration_sec == pytest.approx(raw_main - 4.0)


def test_session_timeline_locate_finds_track_and_local_position():
  tracks = {1: _track(1, duration=60.0), 2: _track(2, duration=60.0)}
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=50.0),
      MixSessionTrack(track_id=2, play_until_sec=40.0),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=50.0,
        crossfade_duration_sec=5.0,
      )
    ],
    start_mode=StartMode.RANDOM,
  )
  timeline = build_session_timeline(session, tracks)
  second_offset = timeline.tracks[1].session_offset_sec
  location = timeline.locate(second_offset + 1.0)

  assert location.track_index == 1
  assert location.local_output_sec == 1.0
