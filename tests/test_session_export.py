from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from engine.domain.enums import AnalysisLevel, StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.export.session_renderer import OUTPUT_SR, export_session, export_session_mp3, export_session_wav, render_session_audio
from engine.playback.timeline_plan import build_session_timeline


def _make_wav(path: Path, duration_sec: float = 1.0, sr: int = 22050) -> None:
  t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
  audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
  sf.write(path, audio, sr)


def _track(track_id: int, path: Path, *, duration: float) -> Track:
  return Track(
    id=track_id,
    path=str(path),
    title=path.stem,
    artist="Test",
    duration=duration,
    file_size=1,
    file_mtime=1.0,
    analysis_level=AnalysisLevel.QUICK,
  )


def test_render_session_audio_matches_timeline(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  _make_wav(first, duration_sec=1.0)
  _make_wav(second, duration_sec=1.0)

  tracks = {
    1: _track(1, first, duration=1.0),
    2: _track(2, second, duration=1.0),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=0.8),
      MixSessionTrack(track_id=2, play_until_sec=0.6),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.CROSSFADE,
        start_at_sec=0.8,
        crossfade_duration_sec=0.2,
      )
    ],
    start_mode=StartMode.WAVE,
  )

  timeline = build_session_timeline(session, tracks)
  audio = render_session_audio(session, tracks)

  assert len(audio) / OUTPUT_SR == pytest.approx(timeline.total_duration_sec, abs=0.05)


def test_export_session_wav_writes_pcm16_file(tmp_path: Path):
  wav_path = tmp_path / "tone.wav"
  _make_wav(wav_path, duration_sec=0.5)

  tracks = {1: _track(1, wav_path, duration=0.5)}
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.5)],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  output = tmp_path / "mix.wav"
  duration = export_session_wav(session, tracks, output)

  assert output.exists()
  assert duration == pytest.approx(0.5, abs=0.05)

  data, sr = sf.read(output, dtype="float32")
  assert sr == OUTPUT_SR
  assert data.ndim == 2
  assert data.shape[1] == 2


def test_export_session_mp3_writes_file(tmp_path: Path):
  wav_path = tmp_path / "tone.wav"
  _make_wav(wav_path, duration_sec=0.5)

  tracks = {1: _track(1, wav_path, duration=0.5)}
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.5)],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  output = tmp_path / "mix.mp3"
  duration = export_session_mp3(session, tracks, output)

  assert output.exists()
  assert duration == pytest.approx(0.5, abs=0.05)
  assert output.stat().st_size > 500

  header = output.read_bytes()[:3]
  assert header == b"ID3" or header[0] == 0xFF


def test_export_session_picks_format_by_extension(tmp_path: Path):
  wav_path = tmp_path / "tone.wav"
  _make_wav(wav_path, duration_sec=0.4)

  tracks = {1: _track(1, wav_path, duration=0.4)}
  session = MixSession(
    tracks=[MixSessionTrack(track_id=1, play_until_sec=0.4)],
    transitions=[],
    start_mode=StartMode.RANDOM,
  )

  mp3_out = tmp_path / "out.mp3"
  wav_out = tmp_path / "out.wav"
  export_session(session, tracks, mp3_out)
  export_session(session, tracks, wav_out)

  assert mp3_out.exists()
  assert wav_out.exists()
