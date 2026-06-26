import pytest

from app.mix_settings import resolve_mix_config, uses_auto_mix_settings
from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import Track
from engine.library.library_profile import (
  CALM_GROOVE_WEIGHT,
  CALM_PLAY_RATIO,
  PEAK_GROOVE_WEIGHT,
  PEAK_PLAY_RATIO,
  WAVE_GROOVE_WEIGHT,
  WAVE_PLAY_RATIO,
  LibraryProfile,
  compute_library_profile,
  profile_tuning_for_mode,
)


def _track(
  track_id: int,
  *,
  bpm: float,
  duration: float = 200.0,
  analysis_level: AnalysisLevel = AnalysisLevel.QUICK,
) -> Track:
  return Track(
    id=track_id,
    path=f"/music/{track_id}.mp3",
    title=f"Track {track_id}",
    artist="Test",
    duration=duration,
    file_size=1000,
    file_mtime=1.0,
    bpm=bpm,
    loudness_avg=-18.0,
    loudness_peak=-12.0,
    content_start_sec=0.0,
    content_end_sec=duration,
    analysis_level=analysis_level,
  )


def _sample_profile() -> LibraryProfile:
  return LibraryProfile(
    track_count=11,
    deep_track_count=11,
    bpm_min=68.0,
    bpm_max=74.0,
    bpm_spread=6.0,
    avg_playable_sec=180.0,
    deep_coverage=1.0,
    calm_track_play_ratio=CALM_PLAY_RATIO,
    calm_groove_weight=CALM_GROOVE_WEIGHT,
    peak_track_play_ratio=PEAK_PLAY_RATIO,
    peak_groove_weight=PEAK_GROOVE_WEIGHT,
    wave_track_play_ratio=WAVE_PLAY_RATIO,
    wave_groove_weight=WAVE_GROOVE_WEIGHT,
    track_play_ratio=PEAK_PLAY_RATIO,
    groove_weight=PEAK_GROOVE_WEIGHT,
    crossfade_duration_sec=8.0,
    session_length_tracks=11,
    computed_at="2026-01-01T00:00:00",
    summary_ru="test",
  )


def test_narrow_bpm_cluster_gets_calibrated_peak_and_calm():
  tracks = [_track(i, bpm=68.0 + i * 0.5, analysis_level=AnalysisLevel.DEEP) for i in range(11)]
  profile = compute_library_profile(tracks)

  assert profile.track_count == 11
  assert profile.bpm_spread == pytest.approx(5.0)
  assert profile.peak_track_play_ratio == PEAK_PLAY_RATIO
  assert profile.peak_groove_weight == PEAK_GROOVE_WEIGHT
  assert profile.calm_track_play_ratio == CALM_PLAY_RATIO
  assert profile.calm_groove_weight == CALM_GROOVE_WEIGHT
  assert profile.wave_track_play_ratio == WAVE_PLAY_RATIO
  assert profile.wave_groove_weight == WAVE_GROOVE_WEIGHT
  assert profile.session_length_tracks == 11
  assert profile.crossfade_duration_sec == 8.0


def test_low_deep_coverage_reduces_groove():
  tracks = [_track(i, bpm=70.0 + i, analysis_level=AnalysisLevel.QUICK) for i in range(6)]
  profile = compute_library_profile(tracks)

  assert profile.deep_coverage == 0.0
  assert profile.peak_groove_weight <= 0.18
  assert profile.calm_groove_weight <= 0.18


def test_profile_tuning_for_mode():
  profile = _sample_profile()

  calm_play, calm_groove = profile_tuning_for_mode(profile, StartMode.CALM)
  peak_play, peak_groove = profile_tuning_for_mode(profile, StartMode.PEAK)

  assert calm_play == CALM_PLAY_RATIO
  assert calm_groove == CALM_GROOVE_WEIGHT
  assert peak_play == PEAK_PLAY_RATIO
  assert peak_groove == PEAK_GROOVE_WEIGHT


def test_resolve_mix_config_uses_calm_profile_when_auto():
  profile = _sample_profile()
  settings = {"mix_settings_manual": False, "session_length_tracks": 5, "groove_weight": 0.1}

  config = resolve_mix_config(settings, profile, mode=StartMode.CALM)

  assert config.session_length == 11
  assert config.track_play_ratio == CALM_PLAY_RATIO
  assert config.groove_weight == CALM_GROOVE_WEIGHT
  assert uses_auto_mix_settings(settings) is True


def test_resolve_mix_config_uses_peak_profile_when_auto():
  profile = _sample_profile()
  settings = {"mix_settings_manual": False}

  config = resolve_mix_config(settings, profile, mode=StartMode.PEAK)

  assert config.track_play_ratio == PEAK_PLAY_RATIO
  assert config.groove_weight == PEAK_GROOVE_WEIGHT


def test_profile_tuning_for_wave_mode():
  profile = _sample_profile()
  wave_play, wave_groove = profile_tuning_for_mode(profile, StartMode.WAVE)
  assert wave_play == WAVE_PLAY_RATIO
  assert wave_groove == WAVE_GROOVE_WEIGHT


def test_resolve_mix_config_uses_wave_profile_when_auto():
  profile = _sample_profile()
  settings = {"mix_settings_manual": False}

  config = resolve_mix_config(settings, profile, mode=StartMode.WAVE)

  assert config.track_play_ratio == WAVE_PLAY_RATIO
  assert config.groove_weight == WAVE_GROOVE_WEIGHT


def test_resolve_mix_config_uses_manual_settings():
  profile = _sample_profile()
  settings = {
    "mix_settings_manual": True,
    "session_length_tracks": 8,
    "crossfade_duration_sec": 10.0,
    "track_play_ratio": 0.8,
    "groove_weight": 0.2,
  }

  config = resolve_mix_config(settings, profile, mode=StartMode.CALM)

  assert config.session_length == 8
  assert config.crossfade_duration_sec == 10.0
  assert config.track_play_ratio == 0.8
  assert config.groove_weight == 0.2
