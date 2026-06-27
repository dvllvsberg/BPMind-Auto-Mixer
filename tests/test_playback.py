from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.playback.audio_loader import load_audio_segment
from engine.playback.session_player import PlayerState, SessionPlayer
from engine.playback.timeline_plan import build_session_timeline


def _make_wav(path: Path, duration_sec: float = 1.0, sr: int = 22050) -> None:
  t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
  audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
  sf.write(path, audio, sr)


def test_load_audio_segment_trims_by_time(tmp_path: Path):
  path = tmp_path / "tone.wav"
  _make_wav(path, duration_sec=2.0)

  data, sr = load_audio_segment(path, start_sec=0.5, end_sec=1.0)

  assert sr == 22050
  assert data.shape[0] == pytest.approx(int(0.5 * sr), abs=2)


def test_session_player_plays_tracks_in_order(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  _make_wav(first, duration_sec=0.2)
  _make_wav(second, duration_sec=0.2)

  tracks = {
    1: Track(
      id=1,
      path=str(first),
      title="A",
      artist="",
      duration=0.2,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
    2: Track(
      id=2,
      path=str(second),
      title="B",
      artist="",
      duration=0.2,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
  }

  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=0.2),
      MixSessionTrack(track_id=2, play_until_sec=0.2),
    ],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  played: list[int] = []

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    player = SessionPlayer(session, tracks)
    original_load = load_audio_segment

    def tracked_load(path, start_sec=0.0, end_sec=None):
      for track_id, track in tracks.items():
        if track.path == str(path):
          played.append(track_id)
      return original_load(path, start_sec, end_sec)

    with (
      patch("engine.playback.session_player.load_audio_segment", side_effect=tracked_load),
      patch("engine.playback.incoming_main.load_audio_segment", side_effect=tracked_load),
    ):
      player.play()
      player.wait_until_finished()

  assert set(played) == {1, 2}
  assert played.index(2) < played.index(1)
  assert player.state == PlayerState.STOPPED


def test_session_player_preloads_incoming_while_playing(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b")]
  for path in paths:
    _make_wav(path, duration_sec=0.3)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=str(track_id),
      artist="",
      duration=0.3,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.3), MixSessionTrack(track_id=2, play_until_sec=0.3)],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.TAPE_STOP,
        start_at_sec=0.3,
        crossfade_duration_sec=0.2,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  preload_calls: list[int] = []
  original_build = SessionPlayer._build_incoming_main_for_index

  def tracked_build(self, index, *, skip_crossfade):
    preload_calls.append(index)
    return original_build(self, index, skip_crossfade=skip_crossfade)

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    with patch.object(SessionPlayer, "_build_incoming_main_for_index", tracked_build):
      player = SessionPlayer(session, tracks)
      player.play()
      player.wait_until_finished()

  assert 1 in preload_calls
  assert preload_calls.index(1) == 0


def test_session_player_seek_clears_handoff_consumed(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  _make_wav(first, duration_sec=1.0)
  _make_wav(second, duration_sec=1.0)

  tracks = {
    1: Track(
      id=1,
      path=str(first),
      title="A",
      artist="",
      duration=1.0,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
    2: Track(
      id=2,
      path=str(second),
      title="B",
      artist="",
      duration=1.0,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
  }
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=1.0), MixSessionTrack(track_id=2, play_until_sec=1.0)],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=1.0,
        crossfade_duration_sec=0.2,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  player = SessionPlayer(session, tracks)
  player.play()
  player._handoff_consumed_index = 1
  timeline = player.timeline
  assert timeline is not None
  target = timeline.tracks[1].session_offset_sec + 0.25
  player.seek_to_session(target)
  assert player._handoff_consumed_index is None


def test_session_player_plays_crossfade_handoff_without_reloading_incoming(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b")]
  for path in paths:
    _make_wav(path, duration_sec=0.4)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=str(track_id),
      artist="",
      duration=0.4,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.4), MixSessionTrack(track_id=2, play_until_sec=0.4)],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=0.4,
        crossfade_duration_sec=0.15,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  load_calls: list[int] = []
  original_load = SessionPlayer._load_incoming_main_for_index

  def tracked_load(self, index, *, skip_crossfade):
    load_calls.append(index)
    return original_load(self, index, skip_crossfade=skip_crossfade)

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    with patch.object(SessionPlayer, "_load_incoming_main_for_index", tracked_load):
      player = SessionPlayer(session, tracks)
      player.play()
      player.wait_until_finished()

  assert load_calls.count(1) == 1


def test_session_player_plays_tape_handoff_without_reloading_incoming(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b")]
  for path in paths:
    _make_wav(path, duration_sec=0.4)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=str(track_id),
      artist="",
      duration=0.4,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.4), MixSessionTrack(track_id=2, play_until_sec=0.4)],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.TAPE_STOP,
        start_at_sec=0.4,
        crossfade_duration_sec=0.2,
      )
    ],
    start_mode=StartMode.RANDOM,
  )

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  load_calls: list[int] = []
  original_load = SessionPlayer._load_incoming_main_for_index

  def tracked_load(self, index, *, skip_crossfade):
    load_calls.append(index)
    return original_load(self, index, skip_crossfade=skip_crossfade)

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    with patch.object(SessionPlayer, "_load_incoming_main_for_index", tracked_load):
      player = SessionPlayer(session, tracks)
      player.play()
      player.wait_until_finished()

  assert load_calls.count(1) == 1


def test_session_player_next_skips_current(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  _make_wav(first, duration_sec=1.0)
  _make_wav(second, duration_sec=0.1)

  tracks = {
    1: Track(
      id=1,
      path=str(first),
      title="A",
      artist="",
      duration=1.0,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
    2: Track(
      id=2,
      path=str(second),
      title="B",
      artist="",
      duration=0.1,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    ),
  }

  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=1.0),
      MixSessionTrack(track_id=2, play_until_sec=0.1),
    ],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    player = SessionPlayer(session, tracks)
    player.play()
    player.next_track()
    player.wait_until_finished()

  assert player.state == PlayerState.STOPPED
  assert player.current_index >= 1


def test_session_player_jump_to_track(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b", "c")]
  for path in paths:
    _make_wav(path, duration_sec=1.0)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=chr(ord("A") + track_id - 1),
      artist="",
      duration=1.0,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }

  session = MixSession(
    tracks=[MixSessionTrack(track_id=i, play_until_sec=1.0) for i in (1, 2, 3)],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  played: list[int] = []

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    original_load = load_audio_segment

    def tracked_load(path, start_sec=0.0, end_sec=None):
      for track_id, track in tracks.items():
        if track.path == str(path):
          played.append(track_id)
      return original_load(path, start_sec, end_sec)

    player = SessionPlayer(session, tracks)
    with (
      patch("engine.playback.session_player.load_audio_segment", side_effect=tracked_load),
      patch("engine.playback.incoming_main.load_audio_segment", side_effect=tracked_load),
    ):
      player.play(start_index=2)
      player.jump_to_track(0)
      player.wait_until_finished()

  assert player.state == PlayerState.STOPPED
  assert {1, 2}.issubset(set(played))


def test_session_player_previous_does_not_skip_past_target(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b", "c")]
  for path in paths:
    _make_wav(path, duration_sec=0.3)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=chr(ord("A") + track_id - 1),
      artist="",
      duration=0.3,
      file_size=1,
      file_mtime=1.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }

  session = MixSession(
    tracks=[MixSessionTrack(track_id=i, play_until_sec=0.3) for i in (1, 2, 3)],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  class FakeStream:
    def __init__(self, *args, **kwargs):
      pass

    def __enter__(self):
      return self

    def __exit__(self, *args):
      return False

    def write(self, data):
      return

  with patch("engine.playback.session_player.sd.OutputStream", FakeStream):
    player = SessionPlayer(session, tracks)
    player.play(start_index=2)
    player.previous_track()
    player.wait_until_finished()

  assert player.state == PlayerState.STOPPED
  assert player.current_index >= 1


def test_current_index_follows_session_position_during_handoff(tmp_path: Path):
  paths = [tmp_path / f"{name}.wav" for name in ("a", "b", "c")]
  for path in paths:
    _make_wav(path, duration_sec=2.0)

  tracks = {
    track_id: Track(
      id=track_id,
      path=str(path),
      title=chr(ord("A") + track_id - 1),
      artist="",
      duration=2.0,
      file_size=1,
      file_mtime=1.0,
      bpm=70.0,
      analysis_level=AnalysisLevel.QUICK,
    )
    for track_id, path in enumerate(paths, start=1)
  }

  session = MixSession(
    tracks=[MixSessionTrack(track_id=i, play_until_sec=2.0) for i in (1, 2, 3)],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.SMOOTH_BLEND,
        start_at_sec=2.0,
        crossfade_duration_sec=0.5,
      ),
      PlannedTransition(
        from_track_id=2,
        to_track_id=3,
        type=TransitionType.SMOOTH_BLEND,
        start_at_sec=2.0,
        crossfade_duration_sec=0.5,
      ),
    ],
    start_mode=StartMode.RANDOM,
  )

  player = SessionPlayer(session, tracks)
  timeline = build_session_timeline(session, tracks, enable_crossfade=True)

  with player._lock:
    player._timeline = timeline
    player._index = 0
    player._state = PlayerState.PLAYING
    player._session_position_sec = timeline.tracks[1].session_offset_sec + 0.25

  assert player.current_index == 1
  now = player.now_playing()
  assert now is not None
  assert now.index == 2
  assert now.track.id == 2

  with player._lock:
    player._state = PlayerState.STOPPED
    player._session_position_sec = timeline.tracks[1].session_offset_sec + 0.25

  assert player.current_index == 0
