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


def test_render_session_audio_matches_timeline_with_reverse_swell_and_silent_head(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  sr = 44100
  duration_sec = 2.0
  t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
  first_audio = (0.25 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
  second_audio = np.zeros_like(first_audio)
  silent = int(0.05 * sr)
  second_audio[silent:] = (0.25 * np.sin(2 * np.pi * 330 * t[silent:])).astype(np.float32)
  sf.write(first, first_audio, sr)
  sf.write(second, second_audio, sr)

  tracks = {
    1: _track(1, first, duration=duration_sec),
    2: _track(2, second, duration=duration_sec),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=1.6),
      MixSessionTrack(track_id=2, play_until_sec=1.4),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.REVERSE_SWELL,
        start_at_sec=1.6,
        crossfade_duration_sec=0.4,
      )
    ],
    start_mode=StartMode.WAVE,
  )

  timeline = build_session_timeline(session, tracks)
  audio = render_session_audio(session, tracks)

  assert len(audio) / OUTPUT_SR == pytest.approx(timeline.total_duration_sec, abs=0.05)


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


def test_opening_track_main_end_not_silent_before_overlap(tmp_path: Path):
  first = tmp_path / "a.wav"
  second = tmp_path / "b.wav"
  _make_wav(first, duration_sec=2.0)
  _make_wav(second, duration_sec=2.0)

  tracks = {
    1: _track(1, first, duration=2.0),
    2: _track(2, second, duration=2.0),
  }
  session = MixSession(
    tracks=[
      MixSessionTrack(track_id=1, play_until_sec=1.6),
      MixSessionTrack(track_id=2, play_until_sec=1.4),
    ],
    transitions=[
      PlannedTransition(
        from_track_id=1,
        to_track_id=2,
        type=TransitionType.IMPACT,
        start_at_sec=1.6,
        crossfade_duration_sec=0.4,
      )
    ],
    start_mode=StartMode.WAVE,
  )

  audio = render_session_audio(session, tracks)
  main_frames = int(round(1.2 * OUTPUT_SR))
  boundary = main_frames
  window = int(0.02 * OUTPUT_SR)
  before = audio[boundary - window : boundary]
  after = audio[boundary : boundary + window]
  before_rms = float(np.sqrt(np.mean(before**2)))
  after_rms = float(np.sqrt(np.mean(after**2)))
  assert before_rms > 0.02
  assert after_rms > before_rms * 0.25


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
