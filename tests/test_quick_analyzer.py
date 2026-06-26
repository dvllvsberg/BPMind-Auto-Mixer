from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from engine.analysis.quick_analysis_runner import QuickAnalysisRunner
from engine.analysis.quick_analyzer import QuickAnalysisResult, analyze_track, estimate_bpm
from engine.database.repository import TrackRepository
from engine.domain.enums import AnalysisLevel


@pytest.fixture
def click_track(tmp_path: Path) -> Path:
  return _make_click_track(tmp_path, "click_120bpm.wav", tempo=120.0)


@pytest.fixture
def slow_click_track(tmp_path: Path) -> Path:
  return _make_click_track(tmp_path, "click_68bpm.wav", tempo=68.0)


def _make_click_track(tmp_path: Path, name: str, tempo: float) -> Path:
  sr = 22050
  duration_sec = 16
  y = np.zeros(sr * duration_sec, dtype=np.float32)
  interval = 60.0 / tempo
  click_len = 800

  for beat_time in np.arange(0, duration_sec, interval):
    start = int(beat_time * sr)
    end = min(start + click_len, len(y))
    t = np.arange(end - start) / sr
    y[start:end] = 0.8 * np.sin(2 * np.pi * 1000 * t) * np.exp(-t * 40)

  path = tmp_path / name
  sf.write(path, y, sr)
  return path


def test_analyze_track_returns_bpm_near_expected(click_track: Path):
  result = analyze_track(click_track)
  assert result.duration == pytest.approx(16.0, abs=0.5)
  assert result.bpm == pytest.approx(120.0, abs=10.0)
  assert result.loudness_avg < result.loudness_peak


def test_estimate_bpm_prefers_slow_tempo_for_half_time_case(slow_click_track: Path):
  import librosa

  y, sr = librosa.load(slow_click_track, sr=None, mono=True)
  bpm = estimate_bpm(y, sr)
  assert bpm == pytest.approx(68.0, abs=8.0)


def test_runner_analyzes_pending_tracks(tmp_path: Path, click_track: Path):
  db = tmp_path / "test.db"
  with TrackRepository(db) as repo:
    repo.upsert_file_record(
      path=str(click_track.resolve()),
      title="Click Test",
      artist="",
      file_size=click_track.stat().st_size,
      file_mtime=click_track.stat().st_mtime,
    )
    runner = QuickAnalysisRunner(repo)
    result = runner.run()

    assert result.total == 1
    assert result.analyzed == 1
    assert result.failed == 0

    track = repo.get_by_path(str(click_track.resolve()))
    assert track is not None
    assert track.analysis_level == AnalysisLevel.QUICK
    assert track.bpm is not None
    assert track.loudness_avg is not None


def test_runner_skips_already_analyzed(tmp_path: Path, click_track: Path):
  db = tmp_path / "test.db"
  with TrackRepository(db) as repo:
    repo.upsert_file_record(
      path=str(click_track.resolve()),
      title="Click Test",
      artist="",
      file_size=click_track.stat().st_size,
      file_mtime=click_track.stat().st_mtime,
    )
    runner = QuickAnalysisRunner(repo)
    runner.run()
    result = runner.run()

    assert result.total == 0
    assert result.analyzed == 0


def test_runner_force_reanalyzes(tmp_path: Path, click_track: Path):
  db = tmp_path / "test.db"
  with TrackRepository(db) as repo:
    repo.upsert_file_record(
      path=str(click_track.resolve()),
      title="Click Test",
      artist="",
      file_size=click_track.stat().st_size,
      file_mtime=click_track.stat().st_mtime,
    )
    runner = QuickAnalysisRunner(repo)
    runner.run()

    with patch("engine.analysis.quick_analysis_runner.analyze_track") as mock_analyze:
      mock_analyze.return_value = QuickAnalysisResult(
        duration=12.0,
        bpm=128.0,
        loudness_avg=-20.0,
        loudness_peak=-3.0,
      )
      result = runner.run(force=True)

    assert result.total == 1
    assert result.analyzed == 1
    track = repo.get_by_path(str(click_track.resolve()))
    assert track is not None
    assert track.bpm == 128.0
