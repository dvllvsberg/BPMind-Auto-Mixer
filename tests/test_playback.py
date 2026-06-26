from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, Track
from engine.playback.audio_loader import load_audio_segment
from engine.playback.session_player import PlayerState, SessionPlayer


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

    with patch("engine.playback.session_player.load_audio_segment", side_effect=tracked_load):
      player.play()
      player.wait_until_finished()

  assert played == [1, 2]
  assert player.state == PlayerState.STOPPED


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
    with patch("engine.playback.session_player.load_audio_segment", side_effect=tracked_load):
      player.play(start_index=2)
      player.jump_to_track(0)
      player.wait_until_finished()

  assert player.state == PlayerState.STOPPED
  first_track_one = played.index(1)
  assert played[first_track_one : first_track_one + 2] == [1, 2]


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
