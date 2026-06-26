import json
from pathlib import Path

import pytest

from engine.domain.enums import AnalysisLevel, StartMode
from engine.domain.models import Track
from engine.mix_generator.bpm_utils import bpm_distance
from engine.mix_generator.mix_generator import MixGenerator, MixGeneratorConfig, MixGeneratorError
from engine.mix_generator.recipe_metadata import MixRecipeMetadata
from engine.mix_generator.session_store import load_mix_recipe, save_mix_recipe


def _track(
  track_id: int,
  title: str,
  *,
  bpm: float,
  loudness: float = -18.0,
  duration: float = 180.0,
  content_start: float = 0.0,
  content_end: float | None = None,
) -> Track:
  return Track(
    id=track_id,
    path=f"/music/{title}.mp3",
    title=title,
    artist="Test",
    duration=duration,
    file_size=1000,
    file_mtime=1.0,
    bpm=bpm,
    loudness_avg=loudness,
    loudness_peak=loudness + 3,
    content_start_sec=content_start,
    content_end_sec=content_end if content_end is not None else duration,
    analysis_level=AnalysisLevel.QUICK,
  )


def test_mix_generator_uses_content_bounds_for_play_range():
  tracks = [
    _track(1, "A", bpm=70.0, duration=200.0, content_start=3.0, content_end=170.0),
    _track(2, "B", bpm=72.0, duration=180.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=2, crossfade_duration_sec=8.0))
  session = generator.generate(tracks, StartMode.RANDOM, seed=1)

  first = session.tracks[0]
  assert first.play_from_sec == 3.0
  assert first.play_until_sec is not None
  assert first.play_until_sec <= 170.0


def test_bpm_distance_treats_half_time_as_compatible():
  assert bpm_distance(68.0, 136.0) == pytest.approx(0.0)
  assert bpm_distance(70.0, 140.0) == pytest.approx(0.0)


def test_mix_generator_uses_all_tracks_when_library_is_small():
  tracks = [
    _track(1, "A", bpm=68.0, loudness=-24.0),
    _track(2, "B", bpm=70.0, loudness=-20.0),
    _track(3, "C", bpm=99.0, loudness=-12.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=12))
  session = generator.generate(tracks, StartMode.CALM, seed=1)

  assert len(session.tracks) == 3
  assert len(session.transitions) == 2
  assert session.tracks[0].track_id == 1


def test_mix_generator_prefers_close_bpm_over_outlier():
  tracks = [
    _track(1, "Start", bpm=69.0, loudness=-20.0, duration=180.0, content_end=160.0),
    _track(2, "Close", bpm=70.0, loudness=-19.0),
    _track(3, "Far", bpm=99.0, loudness=-19.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=2))
  session = generator.generate(tracks, StartMode.FROM_TRACK, start_track_id=1, seed=1)

  assert len(session.tracks) == 2
  assert session.tracks[1].track_id == 2


def test_mix_generator_requires_analyzed_tracks():
  tracks = [Track(id=1, path="/a.mp3", title="A", artist="", duration=None, file_size=1, file_mtime=1.0)]
  generator = MixGenerator()

  with pytest.raises(MixGeneratorError):
    generator.generate(tracks, StartMode.RANDOM)


def test_session_store_roundtrip(tmp_path: Path):
  tracks = [
    _track(1, "A", bpm=68.0),
    _track(2, "B", bpm=70.0),
  ]
  generator = MixGenerator(MixGeneratorConfig(session_length=2))
  session = generator.generate(tracks, StartMode.RANDOM, seed=42)

  path = tmp_path / "mix.json"
  metadata = MixRecipeMetadata(
    track_play_ratio=0.75,
    groove_weight=0.35,
    crossfade_duration_sec=8.0,
    session_length_tracks=2,
  )
  save_mix_recipe(session, path, metadata=metadata)
  loaded = load_mix_recipe(path)[0]

  assert loaded.start_mode == session.start_mode
  assert len(loaded.tracks) == len(session.tracks)
  assert loaded.transitions[0].from_track_id == session.transitions[0].from_track_id

  raw = json.loads(path.read_text(encoding="utf-8"))
  assert raw["start_mode"] == "random"
  assert raw["generator"]["session_length_tracks"] == 2
